"""The provider-agnostic intake core (RADD-951): every decision about an inbound
message happens here, and nothing here knows how it arrived — `sources/` is
transport and authentication only.

The pipeline order is the order the checks must happen in:

    guards   loops first — an autoresponder must not even be deduped
    dedup    before any write, because a retry is the common case
    thread   In-Reply-To → References → subject key → new issue
    write    comment on the matched item, or a new one
    record   the inbound id, so a reply to THIS message threads too

`Outcome` is protocol-free; each transport maps it (HTTP status, a log line).
"""

from __future__ import annotations

import io
import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, ForbiddenError
from radd.mailtypes import MailAttachment
from radd.modules.attachments import service as attachments_service
from radd.modules.attachments.types import AttachmentParentType
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.auth.types import UserSource
from radd.modules.automations.intake import suppressed as intake_suppressed
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.comments import service as comments
from radd.modules.events import service as events
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentOrigin
from radd.modules.items import service as items
from radd.modules.items.enums import ItemOrigin
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import loops, parsing, quoting, routing, service, threading
from .models import MailSource
from .parsing import EmailPlan
from .signatures import detect
from .types import (
    ATTACHMENTS_DROPPED_NOTE,
    ATTACHMENTS_MAX_BYTES,
    AUTH_FAIL_RESULTS,
    AUTH_PASS_RESULT,
    EMAIL_LABEL,
    EMPTY_BODY_PLACEHOLDER,
    MAIL_DROPPED_ID_NAMESPACE,
    MAIL_RAW_RETENTION_DAYS,
    MAX_ATTACHMENTS,
    NO_SUBJECT_TITLE,
    RAW_MESSAGE_CONTENT_TYPE,
    RAW_MESSAGE_FILENAME,
    REPLY_COMMENT_TEMPLATE,
    SENDER_NOTE_TEMPLATE,
    TITLE_MAX_CHARS,
    UNVERIFIED_REPLY_COMMENT_TEMPLATE,
    UNVERIFIED_SENDER_LINE,
    UNVERIFIED_SENDER_NOTE_TEMPLATE,
    MailDirection,
    MailEntity,
    MailEvent,
)

logger = logging.getLogger(__name__)


def _mail_facts(plan: EmailPlan, *, mailbox: str = "", matched_rule: str = "") -> dict:
    """What a rule may condition on (RADD-960/1318) — deliberately NOT the body:
    event payloads are readable by anything that reads the stream, and the body
    already lives behind the item's read gate. `sender_domain` is split out
    because "from a VIP domain" is the condition people write.
    """
    _, _, domain = plan.sender_email.partition("@")
    return {
        "sender": plan.sender_email,
        "sender_domain": domain,
        "sender_name": plan.sender_name,
        "subject": plan.subject,
        "message_id": plan.message_id,
        "html_derived": plan.html_derived,
        "attachment_count": len(plan.attachments),
        "recipients": list(plan.recipients),
        "mailbox": mailbox,
        "matched_rule": matched_rule,
    }


class Result(StrEnum):
    """What happened, in the core's own vocabulary. The transport maps these."""

    CREATED = "created"        # a new issue
    APPENDED = "appended"      # a comment on an existing one
    DUPLICATE = "duplicate"    # this Message-ID was already accepted
    IGNORED = "ignored"        # a loop guard dropped it, deliberately


@dataclass(frozen=True)
class Outcome:
    result: Result
    item_id: uuid.UUID | None = None
    item_key: str = ""
    reason: str = ""
    #: Set when a NEW item was opened by a message we can answer; the caller sends
    #: the receipt AFTER commit (`service.send_ack`).
    ack: "AckPlan | None" = None


@dataclass(frozen=True)
class AckPlan:
    """Everything one receipt needs. No In-Reply-To: the transport resolves it from
    `mail_messages` once the caller has committed the inbound id (RADD-970)."""

    item_id: uuid.UUID
    project_id: uuid.UUID
    email: str
    name: str
    item_key: str
    title: str


@dataclass(frozen=True)
class SenderAuth:
    """Whether the source's TRUSTED gateway vouched for this `From:` (RADD-1032):

        None   the source trusts no authserv-id — `From:` taken at face value
        True   the trusted authserv-id stamped a pass and no fail
        False  it stamped a fail, or nothing at all — DEMOTED to SYSTEM

    `detail` is the human-readable why, shown in the note.
    """

    verified: bool | None
    detail: str = ""

    @property
    def demoted(self) -> bool:
        return self.verified is False


def _check_sender_auth(plan: EmailPlan, trusted_authserv_id: str | None) -> SenderAuth:
    """Read the TRUSTED gateway's SPF/DKIM/DMARC stamp (RADD-1032) — not crypto.
    Absent or failing = demoted: fail-closed."""
    if not trusted_authserv_id:
        return SenderAuth(None)
    verdicts = parsing.parse_auth_results(plan.authentication_results, trusted_authserv_id)
    if not verdicts:
        # None (that authserv stamped nothing) or {} (it spoke but named no
        # method) — either way nothing was proved, and the admin required proof.
        return SenderAuth(False, f"no verdict from {trusted_authserv_id}")
    fails = [f"{m}={r}" for m, r in sorted(verdicts.items()) if r in AUTH_FAIL_RESULTS]
    passed = [m for m, r in verdicts.items() if r == AUTH_PASS_RESULT]
    if fails or not passed:
        detail = ", ".join(fails) if fails else f"no pass from {trusted_authserv_id}"
        return SenderAuth(False, detail)
    return SenderAuth(True, ", ".join(f"{m}={r}" for m, r in sorted(verdicts.items())))


async def _sender_auth(
    session: AsyncSession, plan: EmailPlan, source_id: uuid.UUID | None
) -> SenderAuth:
    """The verdict under the source's trust policy; no source trusts nothing."""
    if source_id is None:
        return SenderAuth(None)
    source = await session.get(MailSource, source_id)
    return _check_sender_auth(plan, source.trusted_authserv_id if source else None)


async def accept(
    session: AsyncSession,
    plan: EmailPlan,
    *,
    raw: bytes,
    default_project_key: str,
    own_addresses: set[str],
    envelope_from: str = "",
    source_id: uuid.UUID | None = None,
    default_project_id: uuid.UUID | None = None,
) -> Outcome:
    """Take one parsed message all the way to an issue or a comment. Raises on
    anything that is Radd's fault; the webhook turns that into a 5xx (a 4xx would
    bounce valid mail)."""
    verdict = loops.check(
        auto_submitted=plan.auto_submitted,
        from_header=plan.from_header,
        envelope_from=envelope_from,
        own_addresses=own_addresses,
    )
    if verdict.drop:
        logger.info("mailintake: dropped message %s — %s", plan.message_id, verdict.reason)
        # Emitted, not only logged: a log line is not queryable (RADD-960).
        await events.emit(
            session,
            event_type=MailEvent.DROPPED,
            entity_type=MailEntity.MAIL,
            entity_id=dropped_entity_id(plan.message_id),
            payload={**_mail_facts(plan), "reason": verdict.reason},
        )
        return Outcome(Result.IGNORED, reason=verdict.reason)

    if await threading.is_duplicate(session, plan.message_id):
        return Outcome(Result.DUPLICATE, reason="Message-ID already accepted")

    sender_auth = await _sender_auth(session, plan, source_id)
    target = await _resolve_thread(session, plan)
    if target is not None:
        return await _append(
            session, plan, raw=raw, item_id=target, source_id=source_id, sender_auth=sender_auth
        )
    # Routing runs ONLY for the first message in a thread (RADD-961).
    return await _create(
        session,
        plan,
        raw=raw,
        default_project_key=default_project_key,
        own_addresses=own_addresses,
        source_id=source_id,
        default_project_id=default_project_id,
        sender_auth=sender_auth,
    )


def dropped_entity_id(message_id: str) -> str:
    """uuid5 over the Message-ID so repeated drops of one message correlate
    (RADD-1035) and fit `entity_id`'s width; uuid4 when there is none."""
    return (
        str(uuid.uuid5(MAIL_DROPPED_ID_NAMESPACE, message_id))
        if message_id
        else str(uuid.uuid4())
    )


async def _resolve_thread(session: AsyncSession, plan: EmailPlan) -> uuid.UUID | None:
    """The issue this message belongs to, or None for a new one.

    Headers first (In-Reply-To, then References), the subject key LAST: headers
    name ids Radd generated and told one person, a key is editable text. The
    subject-key leg is gated on the sender (`_may_thread_by_subject_key`,
    RADD-981); a refused message becomes a new routed issue, not a drop.
    """
    candidates = threading.thread_candidates(plan.in_reply_to, plan.references)
    item_id = await threading.item_for_message_ids(session, candidates)
    if item_id is not None:
        return item_id
    if plan.item_key is not None:
        item = await items.find_item_by_key(session, plan.item_key)
        if item is not None and await _may_thread_by_subject_key(session, item, plan):
            return item.id
    return None


async def _may_thread_by_subject_key(session: AsyncSession, item, plan: EmailPlan) -> bool:
    """Is this sender CONNECTED to the issue their subject key names? (RADD-981/1032)

    A `[PROJ-412]` is a guessable string, so it threads only for: an address
    already on the item's mail thread, the item's reporter, or a real account
    holding UNQUALIFIED `comment.write` on the item's project (staff on that
    desk). Exact membership, not `holds_base` — a bare member's
    `comment.write@own` must not admit them to someone else's ticket; provisioned
    `UserSource.EMAIL` accounts never qualify. A refused message opens a new
    routed issue instead of being dropped; header threading stays ungated.
    """
    if not plan.sender_email:
        return False
    contacts = await service.contacts_for_item(session, item.id)
    if any(contact.email == plan.sender_email for contact in contacts):
        return True
    user = await auth.get_user_by_email(session, plan.sender_email)
    if user is None or not user.active:
        return False
    if user.id == item.reporter_id:
        return True  # the requester, whatever their account is sourced from
    from radd.modules.auth import authz

    if user.source == UserSource.EMAIL.value:
        return False  # a provisioned requester earns nothing from a guessed key
    project = await projects_service.get_project(session, item.project_id)
    if project is None:
        return False
    permissions = await authz.effective_permissions(session, user, project=project)
    # Exact, not `holds_base`: the relation-qualified `comment.write@own` a bare
    # member carries must NOT admit them to a ticket they did not raise.
    return authz.Permission.COMMENT_WRITE in permissions


async def _reply_comment(
    session: AsyncSession, item_id: uuid.UUID, plan: EmailPlan, *, sender_auth: SenderAuth
):
    """Write a mailed reply as a comment and say WHO it is from (RADD-981).

    A REAL account (active, not a provisioned `UserSource.EMAIL` requester)
    authors the comment with the mail verbatim — through `create_comment`,
    which enforces THAT person's `comment.write`, because `From:` is a claim and
    attribution must not become authorisation. Everyone else — a sender who may
    not write there, and any DEMOTED message (RADD-1032) — gets the SYSTEM author
    and the "Email reply from …" prefix. Returns `(comment, author)`.
    """
    # Quotes are stripped from the COMMENT only; the retained raw message keeps
    # them (RADD-1033).
    body = quoting.strip_quotes(plan.body, strip_signature=False) or EMPTY_BODY_PLACEHOLDER
    author = None if sender_auth.demoted else await _reply_author(session, plan)
    if author is not None:
        try:
            comment = await comments.create_comment(
                session, item_id, CommentCreate(body=body), author
            )
            return comment, author
        except ForbiddenError:
            logger.info(
                "mailintake: %s may not comment on %s — attributing the reply to the system",
                plan.sender_email,
                item_id,
            )
    system = await auth.get_user(session, SYSTEM_ACTOR_ID)
    if sender_auth.demoted:
        note = UNVERIFIED_SENDER_LINE.format(detail=sender_auth.detail)
        text = UNVERIFIED_REPLY_COMMENT_TEMPLATE.format(
            note=note, sender=_sender(plan), body=body
        )
    else:
        text = REPLY_COMMENT_TEMPLATE.format(sender=_sender(plan), body=body)
    comment = await comments.create_comment(
        session, item_id, CommentCreate(body=text), system, origin=CommentOrigin.INBOUND_MAIL
    )
    return comment, system


async def _reply_author(session: AsyncSession, plan: EmailPlan) -> User | None:
    """The real account behind a mailed reply, or None for a customer — who is
    still provisioned as a requester by `_sender_user` (RADD-828)."""
    user = await _sender_user(session, plan)
    return user if _is_real(user) else None


async def _append(
    session: AsyncSession,
    plan: EmailPlan,
    *,
    raw: bytes,
    item_id: uuid.UUID,
    source_id: uuid.UUID | None = None,
    sender_auth: SenderAuth,
) -> Outcome:
    comment, actor = await _reply_comment(session, item_id, plan, sender_auth=sender_auth)
    signature, _ = await detect(session, quoting.strip_quotes(plan.body, strip_signature=False), plan.sender_email)
    if signature:
        await comments.annotate_email_signature(session, comment.id, signature)
    await _record_inbound(
        session, plan, raw=raw, item_id=item_id, actor_id=actor.id, source_id=source_id,
        comment_id=getattr(comment, "id", None),
    )
    await _touch_contact(session, item_id, plan)
    item = await items.require_item(session, item_id)
    await events.emit(
        session,
        event_type=MailEvent.RECEIVED,
        entity_type=MailEntity.MAIL,
        entity_id=item_id,
        subjects={"item": item_id},
        payload={**_mail_facts(plan, mailbox=await _mailbox_name(session, source_id)), "created_item": False},
    )
    return Outcome(Result.APPENDED, item_id=item_id, item_key=await _key(session, item))


async def _create(
    session: AsyncSession,
    plan: EmailPlan,
    *,
    raw: bytes,
    default_project_key: str,
    own_addresses: set[str] | None = None,
    source_id: uuid.UUID | None = None,
    default_project_id: uuid.UUID | None = None,
    sender_auth: SenderAuth = SenderAuth(None),
) -> Outcome:
    actor = await auth.get_user(session, SYSTEM_ACTOR_ID)
    project, matched_rule = await _target_project(
        session, plan, default_project_key, source_id, default_project_id
    )
    sender = await _sender_user(session, plan)
    body = plan.body or EMPTY_BODY_PLACEHOLDER
    if sender_auth.demoted:
        # A demoted issue names no reporter (the address may be forged), and its
        # description carries the warning (RADD-1032).
        note = UNVERIFIED_SENDER_LINE.format(detail=sender_auth.detail)
        description = UNVERIFIED_SENDER_NOTE_TEMPLATE.format(
            body=body, note=note, sender=_sender(plan)
        )
        reporter_id = None
    elif sender is not None:
        description = body
        reporter_id = sender.id  # a CLAIM, not an identity (RADD-956) — see below
    else:
        description = SENDER_NOTE_TEMPLATE.format(body=body, sender=_sender(plan))
        reporter_id = None
    # Spec 119: intake checks are suppressed — there is no channel to report a
    # refusal to, so refusing would drop the request silently.
    with intake_suppressed(), items.creating_from(ItemOrigin.EMAIL):
        created = await items.create_item(
            session,
            ItemCreate(
                project_id=project.id,
                title=(plan.subject or NO_SUBJECT_TITLE)[:TITLE_MAX_CHARS],
                description=description,
                labels=[EMAIL_LABEL],
                # A CLAIM, not an identity (RADD-956): `From:` is forgeable, so this
                # names who to write back to and grants nothing.
                reporter_id=reporter_id,
            ),
            actor,
        )
    signature, _ = await detect(session, body, plan.sender_email)
    if signature:
        await items.annotate_email_signature(session, created.id, signature)
    await _record_inbound(
        session, plan, raw=raw, item_id=created.id, actor_id=actor.id, source_id=source_id
    )

    await events.emit(
        session,
        event_type=MailEvent.RECEIVED,
        entity_type=MailEntity.MAIL,
        entity_id=created.id,
        subjects={"item": created.id},
        payload={
            **_mail_facts(plan, mailbox=await _mailbox_name(session, source_id), matched_rule=matched_rule),
            "created_item": True,
        },
    )

    await _capture_contacts(session, created.id, plan, own_addresses=own_addresses or set())
    return Outcome(
        Result.CREATED,
        item_id=created.id,
        item_key=created.key,
        ack=_ack_plan(plan, created, own_addresses or set()),
    )


def _ack_plan(plan: EmailPlan, created, own_addresses: set[str]) -> "AckPlan | None":
    """The receipt for a mail-born issue, or None (RADD-995). It answers a MESSAGE,
    known user or not; refused only for no `From:` or one of our own addresses
    (a loop). Only on CREATE — a receipt per reply would be an autoresponder."""
    if not plan.sender_email or _is_ours(plan.sender_email, own_addresses):
        return None
    return AckPlan(
        item_id=created.id,
        project_id=created.project_id,
        email=plan.sender_email,
        name=plan.sender_name,
        item_key=created.key,
        title=created.title,
    )


async def _capture_contacts(
    session: AsyncSession,
    item_id: uuid.UUID,
    plan: EmailPlan,
    *,
    own_addresses: set[str],
) -> None:
    """Everyone external on the FIRST message becomes a contact (RADD-980).

    The sender is captured as a WRITER (so they become primary); To/Cc are
    `copied_in` (never primary). Skipped: our own addresses, the sender again,
    and real accounts — users are notify's to reach. Account lookups are one
    batched query (RADD-1042).
    """
    known = await auth.users_by_emails(session, [plan.sender_email, *plan.recipients])
    if plan.sender_email and not _is_real(known.get(plan.sender_email)):
        await service.upsert_contact(
            session,
            item_id,
            email=plan.sender_email,
            name=plan.sender_name,
            message_id=plan.message_id or None,
        )
    for address in plan.recipients:
        if _is_ours(address, own_addresses) or address == plan.sender_email:
            continue
        if _is_real(known.get(address)):
            continue
        await service.upsert_contact(session, item_id, email=address, copied_in=True)


def _is_ours(address: str, own_addresses: set[str]) -> bool:
    """Is this one of the desk's own addresses, sub-addressing included? `support+td@`
    is our own alias, but `registry.own_addresses` holds only `support@`."""
    if address in own_addresses:
        return True
    local, _, domain = address.partition("@")
    base, plus, _tag = local.partition("+")
    return bool(plus and domain) and f"{base}@{domain}" in own_addresses


async def _store_attachments(
    session: AsyncSession,
    item_id: uuid.UUID,
    parts: tuple[MailAttachment, ...],
    *,
    actor_id: uuid.UUID,
) -> None:
    """Mail parts become item attachments (spec 102). A failing part is logged and
    skipped — the retained raw message still holds it (RADD-1033)."""
    for part in parts:
        upload = UploadFile(
            file=io.BytesIO(part.data),
            filename=part.filename,
            headers={"content-type": part.content_type},  # type: ignore[arg-type]
        )
        try:
            await attachments_service.save_upload(
                session,
                entity_type=AttachmentParentType.ITEM.value,
                entity_id=item_id,
                upload=upload,
                actor_id=actor_id,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "mailintake: attachment %r could not be stored on %s",
                part.filename,
                item_id,
                exc_info=True,
            )


async def _note_dropped_attachments(
    session: AsyncSession, item_id: uuid.UUID, plan: EmailPlan
) -> None:
    """Leave a SYSTEM note when a per-message cap dropped attachments (RADD-1035);
    failure to write it is swallowed."""
    if plan.attachments_dropped <= 0:
        return
    system = await auth.get_user(session, SYSTEM_ACTOR_ID)
    text = ATTACHMENTS_DROPPED_NOTE.format(
        count=plan.attachments_dropped,
        max_count=MAX_ATTACHMENTS,
        max_mb=ATTACHMENTS_MAX_BYTES // (1024 * 1024),
    )
    try:
        await comments.create_comment(
            session, item_id, CommentCreate(body=text), system, origin=CommentOrigin.INBOUND_MAIL
        )
    except Exception:  # noqa: BLE001 — the receipt is best-effort, the ticket is not
        logger.warning(
            "mailintake: could not note %d dropped attachment(s) on %s",
            plan.attachments_dropped,
            item_id,
            exc_info=True,
        )


async def _retain_raw(session: AsyncSession, message_row, raw: bytes) -> None:
    """Persist the raw bytes against the `mail_messages` row (RADD-1033) as a loose
    blob behind the item's gate. Every skip is silent (retention off, no row, no
    bytes, no storage host) — keeping a copy must never cost the ticket."""
    if message_row is None or MAIL_RAW_RETENTION_DAYS <= 0 or not raw:
        return
    upload = UploadFile(
        file=io.BytesIO(raw),
        filename=RAW_MESSAGE_FILENAME,
        headers={"content-type": RAW_MESSAGE_CONTENT_TYPE},  # type: ignore[arg-type]
    )
    try:
        ref = await attachments_service.save_blob(
            session, upload, content_type=RAW_MESSAGE_CONTENT_TYPE
        )
    except Exception:  # noqa: BLE001 — no default host, unreachable store, etc.
        logger.warning(
            "mailintake: raw message for %s could not be retained",
            message_row.item_id,
            exc_info=True,
        )
        return
    message_row.raw_storage_name = ref.storage_name
    message_row.raw_host_id = ref.host_id
    message_row.raw_size_bytes = ref.size_bytes
    await session.flush()


async def _record_inbound(
    session: AsyncSession,
    plan: EmailPlan,
    *,
    raw: bytes,
    item_id: uuid.UUID,
    actor_id: uuid.UUID,
    source_id: uuid.UUID | None,
    comment_id: uuid.UUID | None = None,
) -> None:
    """What every accepted message leaves on its item: its attachments (and a
    note for any a cap dropped), its `mail_messages` row, the retained raw bytes."""
    await _store_attachments(session, item_id, plan.attachments, actor_id=actor_id)
    await _note_dropped_attachments(session, item_id, plan)
    row = await threading.record(
        session,
        message_id=plan.message_id,
        item_id=item_id,
        direction=MailDirection.INBOUND,
        subject=plan.subject,
        comment_id=comment_id,
        # On every inbound row; the ORIGIN is the earliest (RADD-979), so a mailbox
        # copied in later never takes over the identity replies leave under.
        source_id=source_id,
    )
    await _retain_raw(session, row, raw)


async def _key(session: AsyncSession, item) -> str:
    project = await projects_service.get_project(session, item.project_id)
    return f"{project.key}-{item.number}"


def _sender(plan: EmailPlan) -> str:
    if plan.sender_name and plan.sender_email:
        return f"{plan.sender_name} <{plan.sender_email}>"
    return plan.sender_email or plan.sender_name or "(unknown sender)"


async def _sender_user(session: AsyncSession, plan: EmailPlan) -> User | None:
    """The sender resolved to an ACTIVE user — provisioned when unknown (RADD-828)
    as a `UserSource.EMAIL` account that cannot log in: `From:` is a claim, so an
    account derived from it must never be able to authenticate."""
    if not plan.sender_email:
        return None
    user = await auth.get_user_by_email(session, plan.sender_email)
    if user is not None:
        return user if user.active else None
    user, _created = await auth.ensure_imported_user(
        session,
        email=plan.sender_email,
        name=plan.sender_name or plan.sender_email,
        source=UserSource.EMAIL,
    )
    return user


def _is_real(user: User | None) -> bool:
    """Active and not a provisioned `UserSource.EMAIL` requester (RADD-828)."""
    return user is not None and user.active and user.source != UserSource.EMAIL.value


async def _touch_contact(session: AsyncSession, item_id: uuid.UUID, plan: EmailPlan) -> None:
    """Advance THIS sender's contact row, or add them as a secondary contact —
    unless they are a real account. CC capture is not repeated after the first
    message: only someone who WROTE joins later."""
    if not plan.sender_email:
        return
    # Looks up, never provisions (`_sender_user` would CREATE an account).
    if _is_real(await auth.get_user_by_email(session, plan.sender_email)):
        return  # a colleague replying by mail is a user, reached by notify
    await service.upsert_contact(
        session,
        item_id,
        email=plan.sender_email,
        name=plan.sender_name,
        message_id=plan.message_id or None,
    )


async def _target_project(
    session: AsyncSession,
    plan: EmailPlan,
    default_key: str,
    source_id: uuid.UUID | None = None,
    default_project_id: uuid.UUID | None = None,
) -> tuple[Project, str]:
    """Where a NEW issue opens, and the routing rule that decided it ("" for a
    fallback; RADD-1318), in precedence order (RADD-958/961):

        1. the source's rule chain — alias, sender, subject, then the AI classifier
        2. a plus-address tag (`support+td@`), the spec-62 convention
        3. the source's default project
        4. RADD_MAIL_PROJECT_KEY

    Every layer falls THROUGH — a message must always land.
    """
    decision = await routing.decide(session, plan, source_id=source_id)
    if decision.project_id is not None:
        project = await projects_service.get_project(session, decision.project_id)
        if project is not None:
            logger.info(
                "mailintake: %s → %s (%s)", plan.message_id, project.key, decision.reason
            )
            return project, decision.matched_rule_name or ""
        # A rule naming a deleted project must not swallow the message.
        logger.warning("mailintake: rule %r names a missing project", decision.matched_rule_name)
    projects = await projects_service.list_projects(session)
    if plan.project_key is not None:
        tagged = next((p for p in projects if p.key == plan.project_key), None)
        if tagged is not None:
            return tagged, ""
    if default_project_id is None and source_id is not None:
        source = await session.get(MailSource, source_id)
        default_project_id = source.default_project_id if source else None
    if default_project_id is not None:
        fallback = next((p for p in projects if p.id == default_project_id), None)
        if fallback is not None:
            return fallback, ""
    key = (default_key or "").upper()
    if not key:
        raise ConflictError(MailEntity.MAIL, reason="no default project configured for mail")
    project = next((p for p in projects if p.key == key), None)
    if project is None:
        raise ConflictError(MailEntity.MAIL, reason=f"no project with key {key}")
    return project, ""


async def _mailbox_name(session: AsyncSession, source_id: uuid.UUID | None) -> str:
    """The name of the source a message arrived through, "" for the env webhook."""
    if source_id is None:
        return ""
    source = await session.get(MailSource, source_id)
    return source.name if source is not None else ""
