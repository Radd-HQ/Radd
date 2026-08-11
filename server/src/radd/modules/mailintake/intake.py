"""The provider-agnostic intake core (RADD-951).

**Every decision about an inbound message happens here**, and nothing about it
knows how the message arrived. The webhook source posts raw bytes; the IMAP
poller fetches raw bytes; a Gmail adapter will hand over raw bytes. Logic that
only one of them can reach is precisely the failure the abstraction exists to
avoid, so `sources/` contains transport and authentication and nothing else.

The order of the pipeline is the order the checks have to happen in:

    guards   loops first — an autoresponder must not even be deduped
    dedup    before any write, because a retry is the common case
    thread   In-Reply-To → References → subject key → new issue
    write    comment on the matched item, or a new one
    record   the inbound id, so a reply to THIS message threads too

`Outcome` is what the transports translate into their own vocabulary — HTTP
status for the webhook, a log line for the poller. It never carries an HTTP code
itself: the core has no opinion about a protocol it cannot see.
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
from radd.modules.attachments import service as attachments_service
from radd.modules.attachments.types import AttachmentParentType
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.comments import service as comments
from radd.modules.events import service as events
from radd.modules.comments.schemas import CommentCreate
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import loops, parsing, quoting, routing, service, threading
from .parsing import EmailPlan, MailAttachment
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


def _mail_facts(plan: EmailPlan) -> dict:
    """What a rule may condition on — and deliberately not the body (RADD-960).

    Event payloads are readable by anything that can read the stream, and an
    inbound mail body is customer content that already lives on the item behind
    the item's own read gate. Copying it into the stream would quietly widen who
    can see it, with no screen anywhere admitting that.

    `sender_domain` is split out because "from a VIP domain" is the condition
    people actually write, and asking every rule author to re-derive it from the
    address means half of them get it wrong.
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
    #: Set when a NEW item with an external contact was created — the caller
    #: sends the ack AFTER the transaction commits, never before.
    ack: "AckPlan | None" = None


@dataclass(frozen=True)
class AckPlan:
    """Everything one acknowledgement needs, so a caller reads `outcome.ack` and
    nothing else.

    `item_id` replaced `message_id` (RADD-970). The ack is mailed by the same
    transport as everything else now, and that resolves In-Reply-To from
    `mail_messages` — which already holds the inbound id recorded a few lines
    above, in the transaction the caller commits before acking. Carrying the id
    onward as well would be a second copy of a fact the store owns.
    """

    item_id: uuid.UUID
    email: str
    name: str
    item_key: str
    title: str


@dataclass(frozen=True)
class SenderAuth:
    """Whether the source's TRUSTED gateway vouched for this `From:` (RADD-1032).

    `verified` is a tri-state on purpose:

        None   the source trusts no authserv-id — today's behaviour exactly, so
               `From:` is taken at face value and existing installs are unchanged.
        True   the trusted authserv-id stamped a pass and no fail.
        False  it stamped a fail, or said nothing at all (absent when required).

    Only False DEMOTES: the message is recorded as received but attributed to
    SYSTEM, never to the account whose address it may have forged. `detail` is the
    human-readable why, shown in the note.
    """

    verified: bool | None
    detail: str = ""

    @property
    def demoted(self) -> bool:
        return self.verified is False


def _check_sender_auth(plan: EmailPlan, trusted_authserv_id: str | None) -> SenderAuth:
    """Read the trusted gateway's verdict for this message (RADD-1032, pure).

    Radd is not doing crypto here — it is reading the SPF/DKIM/DMARC verdict its
    own MX already stamped, and trusting that stamp because the admin named the
    authserv-id it comes from. A message with no such stamp, or one showing a
    fail, is not trusted: fail-closed, because the entire point is to stop a
    forged `From:` speaking as a real account.
    """
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
    """The verdict for this message under its source's trust policy (RADD-1032).

    Loads the source once to read `trusted_authserv_id`; a message with no source
    (a direct `accept` in a test, or the env-only path) trusts nothing and so
    behaves exactly as before.
    """
    if source_id is None:
        return SenderAuth(None)
    from .models import MailSource

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
    """Take one parsed message all the way to an issue or a comment.

    Raises on anything that is Radd's fault (a database failure, an unresolvable
    default project). The webhook turns those into 5xx — a 4xx there would bounce
    valid mail and tell the sender their message was rejected by policy when it
    was in fact dropped by an outage.
    """
    verdict = loops.check(
        auto_submitted=plan.auto_submitted,
        from_header=plan.from_header,
        envelope_from=envelope_from,
        own_addresses=own_addresses,
    )
    if verdict.drop:
        logger.info("mailintake: dropped message %s — %s", plan.message_id, verdict.reason)
        # Emitted, not only logged: a silent drop and a bug are indistinguishable
        # from outside, and a log line is not queryable (RADD-960). The id is
        # correlatable off the Message-ID (RADD-1035), so a retried loop is one
        # id, not a fresh uuid4 per delivery.
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
    # Routing runs ONLY here — the first message in a thread. A reply resolved
    # above and never reaches the chain, so the AI classifier can never
    # re-decide the project on message four (RADD-961).
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
    """A correlatable `entity_id` for a `mail.dropped` event (RADD-1035).

    A repeated drop of the SAME message — a provider retrying a message the loop
    guard keeps rejecting — should be ONE id, not a scatter of uuid4s nobody can
    group. So it is uuid5 over the Message-ID. A message with none has nothing to
    correlate on and falls back to uuid4. Also keeps the value inside the events
    table's `entity_id` width, which a verbatim Message-ID can overflow.
    """
    return (
        str(uuid.uuid5(MAIL_DROPPED_ID_NAMESPACE, message_id))
        if message_id
        else str(uuid.uuid4())
    )


async def _resolve_thread(session: AsyncSession, plan: EmailPlan) -> uuid.UUID | None:
    """The issue this message belongs to, or None for a new one.

    Headers first and the subject key LAST — the reverse of what shipped in
    spec 47, where the subject key was the only mechanism. A reply whose subject
    key names a different issue than its headers follows the headers: the key is
    text a human can edit or a list can mangle, the headers are what the client
    generated.

    **The subject-key leg is gated on the sender (RADD-981).** Header threading
    is not: an `In-Reply-To` names an id Radd generated and told exactly one
    person, so possessing it is itself the evidence. `[PROJ-412]` is not — it is
    a guessable string in a text field, and any stranger who typed it wrote
    straight into somebody else's ticket, where the outbound consumer then
    mailed their words to that ticket's requester. `_may_thread_by_subject_key`
    is what closes that; a refused message becomes a NEW routed issue rather
    than being dropped, because a stranger with the wrong subject line is still
    a person asking for help.
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
    """Is this sender CONNECTED to the issue their subject line names? (RADD-1032)

    A `[PROJ-412]` in a subject is a guessable string in a text field, and keys
    are sequential — so on its own it is evidence of nothing. It threads only for
    someone the conversation already belongs to:

        an address already on the item's mail thread   they are in the conversation
        the item's reporter                            they raised it
        a real account that can WRITE on the project    staff working that desk

    The last leg is the narrowing. It used to admit ANY active real account
    instance-wide — so one email to the desk earned a stranger the right to type
    into every ticket whose key they could guess, and the outbound consumer then
    mailed their words to that ticket's requester. The UNQUALIFIED `comment.write`
    on the item's OWN project is the honest test for "staff who work this desk":
    a project member with the Member/Agent role holds it, while a bare member
    holds only the relation-qualified `comment.write@own` / `@participant` — which
    lets them comment on their OWN items, not type into a stranger's — and every
    `UserSource.EMAIL` account intake provisions for a customer (RADD-828) is
    excluded outright. The exact-membership test is deliberate: `holds_base` would
    count `comment.write@own` as the base and re-admit every member (the
    "holds_base is for gates, not summaries" trap). It is also, by construction,
    the set an item-watcher leg would admit — a colleague watching a ticket they
    can act on holds this atom already.

    A refused message is NOT dropped: `_resolve_thread` opens the stranger a new
    routed issue, because a wrong subject line is still a person asking for help.
    Header threading stays ungated (see `_resolve_thread`) — an `In-Reply-To`
    names an id Radd generated and told exactly one person.
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
    from radd.modules.auth.types import UserSource

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
    """Write the mailed reply as a comment, and say WHO it is from (RADD-981).

    Every inbound reply used to be authored by the SYSTEM actor with the sender
    named in a `Email reply from …:` line of the body. For a customer with no
    account that is the only honest answer. For a colleague replying to a
    notification it was wrong in four places at once, all of them invisible from
    the diff: the issue read as if a robot had spoken, the outbound consumer's
    SYSTEM gate refused to relay it to the requester, the SLA response timer
    skipped it as a non-answer, and — because notify excludes the ACTOR — the
    agent was notified of their own comment while nobody else's exclusion
    applied.

    So a REAL account (active, not one of the `UserSource.EMAIL` accounts intake
    provisions) becomes the comment's author and the body is the mail, verbatim.
    Everyone else keeps the SYSTEM attribution and the prefix.

    **Attribution is not authorisation.** `From:` is forgeable — the header this
    whole module treats as a claim — so the comment goes through
    `create_comment`, which enforces that person's own `comment.write` on that
    project, rather than the caller-authorised seam. A sender who cannot write
    there falls back to SYSTEM: the message still lands, and nothing was granted
    on the strength of a header. Returns `(comment, author)`; the author is what
    the attachments are stored as, so the mail arrives as one person's act.

    **A DEMOTED message never reaches `_reply_author` at all (RADD-1032).** When
    the source trusts an authserv-id and this message failed or lacked its
    verdict, `From:` is not merely unauthorised, it is unverified — so the reply
    is a SYSTEM comment that leads with the unverified-sender warning, and no
    real account is ever named as its author.
    """
    # Quoted history is stripped from the COMMENT only; the RAW message is
    # retained by the caller per `MAIL_RAW_RETENTION_DAYS` (RADD-1033), so an
    # over-eager strip is recoverable for the retention window.
    body = quoting.strip_quotes(plan.body) or EMPTY_BODY_PLACEHOLDER
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
    comment = await comments.create_comment(session, item_id, CommentCreate(body=text), system)
    return comment, system


async def _reply_author(session: AsyncSession, plan: EmailPlan) -> User | None:
    """The real account behind a mailed reply, or None for a customer.

    `_sender_user` still runs — an unknown sender is still provisioned as a
    requester (RADD-828), which is what makes them addressable at all — and this
    only decides whether that account is a person Radd already knew.
    """
    user = await _sender_user(session, plan)
    if user is None:
        return None
    from radd.modules.auth.types import UserSource

    return None if user.source == UserSource.EMAIL.value else user


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
    await _store_attachments(session, item_id, plan.attachments, actor_id=actor.id)
    await _note_dropped_attachments(session, item_id, plan)
    row = await threading.record(
        session,
        message_id=plan.message_id,
        item_id=item_id,
        direction=MailDirection.INBOUND,
        subject=plan.subject,
        comment_id=getattr(comment, "id", None),
        # The source is recorded on every inbound row, replies included
        # (RADD-979) — but the ORIGIN is the earliest of them, so a mailbox
        # copied in later never takes over the identity replies leave under.
        source_id=source_id,
    )
    await _retain_raw(session, row, raw)
    await _touch_contact(session, item_id, plan)
    item = await items.require_item(session, item_id)
    await events.emit(
        session,
        event_type=MailEvent.RECEIVED,
        entity_type=MailEntity.MAIL,
        entity_id=item_id,
        subjects={"item": item_id},
        payload={**_mail_facts(plan), "created_item": False},
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
    project = await _target_project(
        session, plan, default_project_key, source_id, default_project_id
    )
    sender = await _sender_user(session, plan)
    body = plan.body or EMPTY_BODY_PLACEHOLDER
    if sender_auth.demoted:
        # A trusted gateway said this From is fail-or-absent (RADD-1032). The
        # reporter is only ever a mailback claim, but pinning it to the account
        # whose address may be forged still asserts an identity — so a demoted
        # issue names no reporter, and its description carries the warning.
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
    created = await items.create_item(
        session,
        ItemCreate(
            project_id=project.id,
            title=(plan.subject or NO_SUBJECT_TITLE)[:TITLE_MAX_CHARS],
            description=description,
            labels=[EMAIL_LABEL],
            # The reporter is a CLAIM, not an identity (RADD-956). `From:` is
            # trivially forged, so this names who to write back to and grants
            # nothing — `_sender_user` provisions an account that cannot log in.
            reporter_id=reporter_id,
        ),
        actor,
    )
    await _store_attachments(session, created.id, plan.attachments, actor_id=actor.id)
    await _note_dropped_attachments(session, created.id, plan)
    row = await threading.record(
        session,
        message_id=plan.message_id,
        item_id=created.id,
        direction=MailDirection.INBOUND,
        subject=plan.subject,
        # The item's mail ORIGIN (RADD-979): this row is the earliest inbound
        # one by construction, so it is what decides the reply identity.
        source_id=source_id,
    )
    await _retain_raw(session, row, raw)

    await events.emit(
        session,
        event_type=MailEvent.RECEIVED,
        entity_type=MailEntity.MAIL,
        entity_id=created.id,
        subjects={"item": created.id},
        payload={**_mail_facts(plan), "created_item": True},
    )

    await _capture_contacts(session, created.id, plan, own_addresses=own_addresses or set())
    return Outcome(
        Result.CREATED,
        item_id=created.id,
        item_key=created.key,
        # RADD-995: the receipt is a property of the MESSAGE, not of the sender's
        # account status — see `_ack_plan`.
        ack=_ack_plan(plan, created, own_addresses or set()),
    )


def _ack_plan(plan: EmailPlan, created, own_addresses: set[str]) -> "AckPlan | None":
    """The acknowledgement for a mail-born issue, or None (RADD-995).

    **It used to be a contact feature**, and that was the bug: the ack was
    planned only on the branch that captured a `mail_contact`, so an ordinary
    recognised user — an OIDC colleague mailing the desk — became the reporter,
    got no contact row, and received nothing at all. Silently, because every
    other part of that path worked.

    A receipt answers a MESSAGE. Whoever sent it gets one, account or not; the
    only refusals are an address we cannot answer (no `From:`) and one of our
    own, which would be a mail loop with a friendly subject line. The loop
    guards already dropped that message before `_create` ran — this is the same
    judgment restated at the point that would compose the reply, so the ack can
    never become the one path that re-opens the loop.

    Still gated on `mail_send_ack` inside `send_ack`, and still only on CREATE:
    an ack per reply would be an autoresponder.
    """
    if not plan.sender_email or _is_ours(plan.sender_email, own_addresses):
        return None
    return AckPlan(
        item_id=created.id,
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

    The sender is captured first and as a WRITER, which is what makes them the
    item's primary contact; the To/Cc addresses are captured `copied_in`, which
    is what stops one of them inheriting that badge on a ticket a colleague
    raised by mail.

    Three exclusions on the recipient sweep, each for its own reason: our OWN
    addresses (we are not a party to the conversation, we are the desk), the
    sender (already captured, and their `From:` need not match the `To:` they
    used), and any address belonging to a REAL account — a copied-in colleague
    is a user, and users are reached by notify through the rows that decide
    their inbox. Mailing them from here as well would be the duplicate fan-out
    RADD-968 deleted.

    The account lookups are ONE `WHERE email IN (...)` (RADD-1042): the sweep
    used to run a `get_user_by_email` per recipient, a query per CC on the hot
    path of every first message. Byte-identical to the per-address version — the
    same predicate, resolved from one dict.
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
    """Is this one of the desk's own addresses, sub-addressing included?

    `support+td@` is spec 62's plus-address routing convention and therefore
    expected traffic on the To line, but `registry.own_addresses` holds the
    mailbox (`support@`) — so a literal comparison files our own alias as an
    external requester, puts it in the issue rail, and mails it every reply.
    """
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
    """Mail parts become Radd attachments through the spec-102 polymorphic seam.

    One failing part is logged and skipped rather than failing the message: a
    ticket with three of four attachments beats a bounce, and — when retention is
    on — the raw message is kept regardless (RADD-1033), so a dropped part is
    still recoverable from the stored bytes for the retention window.
    """
    for part in parts:
        upload = UploadFile(
            file=io.BytesIO(part.content),
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
    """Leave a note when a per-message cap swallowed attachments (RADD-1035).

    `parsing` counts them; the note lives HERE because the item — the only place
    a note can attach to — exists only at this point. A SYSTEM comment, because
    the loss is Radd's cap talking, not the sender's. Nothing is written when
    nothing was dropped, so the ordinary message pays neither a comment nor a
    query. A failure to write the note is logged and swallowed: a receipt about
    lost attachments must not itself cost the message.
    """
    if plan.attachments_dropped <= 0:
        return
    system = await auth.get_user(session, SYSTEM_ACTOR_ID)
    text = ATTACHMENTS_DROPPED_NOTE.format(
        count=plan.attachments_dropped,
        max_count=MAX_ATTACHMENTS,
        max_mb=ATTACHMENTS_MAX_BYTES // (1024 * 1024),
    )
    try:
        await comments.create_comment(session, item_id, CommentCreate(body=text), system)
    except Exception:  # noqa: BLE001 — the receipt is best-effort, the ticket is not
        logger.warning(
            "mailintake: could not note %d dropped attachment(s) on %s",
            plan.attachments_dropped,
            item_id,
            exc_info=True,
        )


async def _retain_raw(session: AsyncSession, message_row, raw: bytes) -> None:
    """Persist the raw inbound bytes against their `mail_messages` row (RADD-1033).

    Behind `MAIL_RAW_RETENTION_DAYS` and stored as one loose blob through the
    spec-102 seam, keyed off the message row so a reader reaches it the way it
    reaches an attachment — through the item's own gate. Every skip is silent and
    the mail still lands: retention off (0), no row to key off (no Message-ID, or
    a concurrent-retry duplicate `record` answered None), empty bytes (a test),
    or no storage host configured. Keeping a copy of the mail must never be the
    thing that costs the customer their ticket.
    """
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


async def _key(session: AsyncSession, item) -> str:
    project = await projects_service.get_project(session, item.project_id)
    return f"{project.key}-{item.number}"


def _sender(plan: EmailPlan) -> str:
    if plan.sender_name and plan.sender_email:
        return f"{plan.sender_name} <{plan.sender_email}>"
    return plan.sender_email or plan.sender_name or "(unknown sender)"


async def _sender_user(session: AsyncSession, plan: EmailPlan) -> User | None:
    """The sender resolved to an ACTIVE user — provisioned when unknown
    (RADD-828): a `UserSource.EMAIL` account that cannot log in and whose floor
    is the seeded Requester role. That property is load-bearing: `From:` is a
    claim, so an account derived from it must never be able to authenticate."""
    if not plan.sender_email:
        return None
    user = await auth.get_user_by_email(session, plan.sender_email)
    if user is not None:
        return user if user.active else None
    from radd.modules.auth.types import UserSource

    user, _created = await auth.ensure_imported_user(
        session,
        email=plan.sender_email,
        name=plan.sender_name or plan.sender_email,
        source=UserSource.EMAIL,
    )
    return user


def _is_real(user: User | None) -> bool:
    """Is this resolved account a genuine person, not a provisioned requester?

    ACTIVE, and NOT one of the `UserSource.EMAIL` accounts intake provisions for
    unknown senders (RADD-828) — those exist precisely so a customer has a
    reporter id, and treating one as staff would delete the contact row that is
    the only way to write back to them. Pure so a BATCH caller (`_capture_contacts`,
    RADD-1042) can apply the same predicate to a user it already resolved.
    """
    from radd.modules.auth.types import UserSource

    return user is not None and user.active and user.source != UserSource.EMAIL.value


async def _is_real_account(session: AsyncSession, email: str) -> bool:
    """Does this address belong to a person with a genuine Radd account?

    **It looks up; it never provisions.** That distinction is the RADD-980 bug
    it replaces: `_touch_contact` asked `_sender_user(...) is None`, and that
    function CREATES an account for an unknown address — so the test it was
    guarding could effectively never be true, and a second sender on a thread
    was never recorded.
    """
    return _is_real(await auth.get_user_by_email(session, email))


async def _touch_contact(session: AsyncSession, item_id: uuid.UUID, plan: EmailPlan) -> None:
    """Advance THIS sender's contact row, or open one for a new external voice.

    Both halves changed in RADD-980. `last_message_id` used to be advanced on
    whichever single contact the item had, whoever had actually written — one
    column standing in for three people's threads. And a genuinely new external
    sender is now recorded as a secondary contact instead of being dropped, so
    the colleague a customer looped in hears the answer too.

    CC capture is deliberately NOT repeated here. A reply's `To:` line carries
    everyone the mail client happened to keep, including addresses that were
    dropped from the conversation on purpose; only somebody who actually WROTE
    joins the thread after the first message.
    """
    if not plan.sender_email:
        return
    if await _is_real_account(session, plan.sender_email):
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
) -> Project:
    """Where a NEW issue opens, in precedence order (RADD-958/961):

        1. the source's rule chain — alias, sender, subject, then the AI classifier
        2. a plus-address tag (`support+td@`), the spec-62 convention
        3. the source's default project
        4. RADD_MAIL_PROJECT_KEY

    The chain is first, because it is the configured, visible answer; the plus
    tag stays underneath it so anything already using `support+td@` keeps
    working. Every layer falls THROUGH rather than failing — a message must
    always land somewhere.
    """
    decision = await routing.decide(session, plan, source_id=source_id)
    if decision.project_id is not None:
        project = await projects_service.get_project(session, decision.project_id)
        if project is not None:
            logger.info(
                "mailintake: %s → %s (%s)", plan.message_id, project.key, decision.reason
            )
            return project
        # A rule naming a deleted project must not swallow the message.
        logger.warning("mailintake: rule %r names a missing project", decision.matched_rule_name)
    projects = await projects_service.list_projects(session)
    if plan.project_key is not None:
        tagged = next((p for p in projects if p.key == plan.project_key), None)
        if tagged is not None:
            return tagged
    if default_project_id is None and source_id is not None:
        from .models import MailSource

        source = await session.get(MailSource, source_id)
        default_project_id = source.default_project_id if source else None
    if default_project_id is not None:
        fallback = next((p for p in projects if p.id == default_project_id), None)
        if fallback is not None:
            return fallback
    key = (default_key or "").upper()
    if not key:
        raise ConflictError(MailEntity.MAIL, reason="no default project configured for mail")
    project = next((p for p in projects if p.key == key), None)
    if project is None:
        raise ConflictError(MailEntity.MAIL, reason=f"no project with key {key}")
    return project
