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

from radd.exceptions import ConflictError
from radd.modules.attachments import service as attachments_service
from radd.modules.attachments.types import AttachmentParentType
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.comments import service as comments
from radd.modules.comments.schemas import CommentCreate
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import loops, quoting, service, threading
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
)

logger = logging.getLogger(__name__)


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
    email: str
    name: str
    item_key: str
    title: str
    message_id: str


async def accept(
    session: AsyncSession,
    plan: EmailPlan,
    *,
    raw: bytes,
    default_project_key: str,
    own_addresses: set[str],
    envelope_from: str = "",
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
        return Outcome(Result.IGNORED, reason=verdict.reason)

    if await threading.is_duplicate(session, plan.message_id):
        return Outcome(Result.DUPLICATE, reason="Message-ID already accepted")

    target = await _resolve_thread(session, plan)
    if target is not None:
        return await _append(session, plan, raw=raw, item_id=target)
    return await _create(session, plan, raw=raw, default_project_key=default_project_key)


async def _resolve_thread(session: AsyncSession, plan: EmailPlan) -> uuid.UUID | None:
    """The issue this message belongs to, or None for a new one.

    Headers first and the subject key LAST — the reverse of what shipped in
    spec 47, where the subject key was the only mechanism. A reply whose subject
    key names a different issue than its headers follows the headers: the key is
    text a human can edit or a list can mangle, the headers are what the client
    generated.
    """
    candidates = threading.thread_candidates(plan.in_reply_to, plan.references)
    item_id = await threading.item_for_message_ids(session, candidates)
    if item_id is not None:
        return item_id
    if plan.item_key is not None:
        item = await items.find_item_by_key(session, plan.item_key)
        if item is not None:
            return item.id
    return None


async def _append(
    session: AsyncSession, plan: EmailPlan, *, raw: bytes, item_id: uuid.UUID
) -> Outcome:
    actor = await auth.get_user(session, SYSTEM_ACTOR_ID)
    # Quoted history is stripped from the COMMENT only; `raw` is retained by the
    # caller, so an over-eager strip is recoverable.
    body = quoting.strip_quotes(plan.body) or EMPTY_BODY_PLACEHOLDER
    comment = await comments.create_comment(
        session,
        item_id,
        CommentCreate(body=REPLY_COMMENT_TEMPLATE.format(sender=_sender(plan), body=body)),
        actor,
    )
    await _store_attachments(session, item_id, plan.attachments, actor_id=actor.id)
    await threading.record(
        session,
        message_id=plan.message_id,
        item_id=item_id,
        direction=MailDirection.INBOUND,
        subject=plan.subject,
        comment_id=getattr(comment, "id", None),
    )
    await _touch_contact(session, item_id, plan)
    item = await items.require_item(session, item_id)
    return Outcome(Result.APPENDED, item_id=item_id, item_key=await _key(session, item))


async def _create(
    session: AsyncSession, plan: EmailPlan, *, raw: bytes, default_project_key: str
) -> Outcome:
    actor = await auth.get_user(session, SYSTEM_ACTOR_ID)
    project = await _target_project(session, plan, default_project_key)
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
    )

    from radd.modules.auth.types import UserSource

    email_sourced = sender is not None and sender.source == UserSource.EMAIL.value
    if (sender is not None and not email_sourced) or not plan.sender_email:
        return Outcome(Result.CREATED, item_id=created.id, item_key=created.key)
    await service.upsert_contact(
        session,
        created.id,
        email=plan.sender_email,
        name=plan.sender_name,
        message_id=plan.message_id or None,
    )
    return Outcome(
        Result.CREATED,
        item_id=created.id,
        item_key=created.key,
        ack=AckPlan(
            email=plan.sender_email,
            name=plan.sender_name,
            item_key=created.key,
            title=created.title,
            message_id=plan.message_id,
        ),
    )


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


async def _touch_contact(session: AsyncSession, item_id: uuid.UUID, plan: EmailPlan) -> None:
    contact = await service.contact_for_item(session, item_id)
    if contact is not None:
        await service.upsert_contact(
            session, item_id, email=contact.email, message_id=plan.message_id or None
        )
        return
    if plan.sender_email and await _sender_user(session, plan) is None:
        await service.upsert_contact(
            session,
            item_id,
            email=plan.sender_email,
            name=plan.sender_name,
            message_id=plan.message_id or None,
        )


async def _target_project(
    session: AsyncSession, plan: EmailPlan, default_key: str
) -> Project:
    """Plus-address routing (spec 62) for a FIRST contact — `support+td@…` opens
    in project TD. This is routing, not threading: an unknown tag falls back to
    the default rather than failing, which is why plus-addressing is acceptable
    here and not as the threading mechanism (RADD-954)."""
    projects = await projects_service.list_projects(session)
    if plan.project_key is not None:
        tagged = next((p for p in projects if p.key == plan.project_key), None)
        if tagged is not None:
            return tagged
    key = (default_key or "").upper()
    if not key:
        raise ConflictError(MailEntity.MAIL, reason="no default project configured for mail")
    project = next((p for p in projects if p.key == key), None)
    if project is None:
        raise ConflictError(MailEntity.MAIL, reason=f"no project with key {key}")
    return project
