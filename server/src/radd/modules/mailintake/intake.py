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

from . import loops, quoting, routing, service, threading
from .parsing import EmailPlan, MailAttachment
from .types import (
    EMAIL_LABEL,
    EMPTY_BODY_PLACEHOLDER,
    NO_SUBJECT_TITLE,
    REPLY_COMMENT_TEMPLATE,
    SENDER_NOTE_TEMPLATE,
    TITLE_MAX_CHARS,
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
        # from outside, and a log line is not queryable (RADD-960).
        await events.emit(
            session,
            event_type=MailEvent.DROPPED,
            entity_type=MailEntity.MAIL,
            entity_id=uuid.uuid4(),
            payload={**_mail_facts(plan), "reason": verdict.reason},
        )
        return Outcome(Result.IGNORED, reason=verdict.reason)

    if await threading.is_duplicate(session, plan.message_id):
        return Outcome(Result.DUPLICATE, reason="Message-ID already accepted")

    target = await _resolve_thread(session, plan)
    if target is not None:
        return await _append(session, plan, raw=raw, item_id=target, source_id=source_id)
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
    """Is this sender entitled to write into the issue their subject line names?

    Three ways to be, in the order they cost a query:

        an address already on the item's mail thread   they are in the conversation
        the item's reporter                            they raised it
        any active REAL account                        staff, on any ticket

    The third is broad on purpose: an agent forwarding a ticket to a colleague,
    or replying from a phone that mangled the headers, must not be told their
    mail opened a duplicate. What it excludes is the case that matters — a
    `UserSource.EMAIL` account, which is what an unknown sender is provisioned
    as (RADD-828). Otherwise one email to the desk would earn a stranger the
    right to type into every issue whose key they can guess, and keys are
    sequential.
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
    from radd.modules.auth.types import UserSource

    return user.source != UserSource.EMAIL.value


async def _reply_comment(session: AsyncSession, item_id: uuid.UUID, plan: EmailPlan):
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
    """
    # Quoted history is stripped from the COMMENT only; `raw` is retained by the
    # caller, so an over-eager strip is recoverable.
    body = quoting.strip_quotes(plan.body) or EMPTY_BODY_PLACEHOLDER
    author = await _reply_author(session, plan)
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
    comment = await comments.create_comment(
        session,
        item_id,
        CommentCreate(body=REPLY_COMMENT_TEMPLATE.format(sender=_sender(plan), body=body)),
        system,
    )
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
) -> Outcome:
    comment, actor = await _reply_comment(session, item_id, plan)
    await _store_attachments(session, item_id, plan.attachments, actor_id=actor.id)
    await threading.record(
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
) -> Outcome:
    actor = await auth.get_user(session, SYSTEM_ACTOR_ID)
    project = await _target_project(
        session, plan, default_project_key, source_id, default_project_id
    )
    sender = await _sender_user(session, plan)
    body = plan.body or EMPTY_BODY_PLACEHOLDER
    description = body if sender is not None else SENDER_NOTE_TEMPLATE.format(
        body=body, sender=_sender(plan)
    )
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
            reporter_id=sender.id if sender is not None else None,
        ),
        actor,
    )
    await _store_attachments(session, created.id, plan.attachments, actor_id=actor.id)
    await threading.record(
        session,
        message_id=plan.message_id,
        item_id=created.id,
        direction=MailDirection.INBOUND,
        subject=plan.subject,
        # The item's mail ORIGIN (RADD-979): this row is the earliest inbound
        # one by construction, so it is what decides the reply identity.
        source_id=source_id,
    )

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
    """
    if plan.sender_email and not await _is_real_account(session, plan.sender_email):
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
        if await _is_real_account(session, address):
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
    ticket with three of four attachments beats a bounce, and the raw message is
    retained either way.
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


async def _is_real_account(session: AsyncSession, email: str) -> bool:
    """Does this address belong to a person with a genuine Radd account?

    ACTIVE, and NOT one of the `UserSource.EMAIL` accounts intake provisions for
    unknown senders (RADD-828) — those exist precisely so a customer has a
    reporter id, and treating one as staff would delete the contact row that is
    the only way to write back to them.

    **It looks up; it never provisions.** That distinction is the RADD-980 bug
    it replaces: `_touch_contact` asked `_sender_user(...) is None`, and that
    function CREATES an account for an unknown address — so the test it was
    guarding could effectively never be true, and a second sender on a thread
    was never recorded.
    """
    from radd.modules.auth.types import UserSource

    user = await auth.get_user_by_email(session, email)
    return user is not None and user.active and user.source != UserSource.EMAIL.value


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
