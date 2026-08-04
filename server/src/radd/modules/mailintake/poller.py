"""IMAP poll + intake (specs 47+62). The blocking imaplib calls run in a worker
thread (asyncio.to_thread); the item/comment writes run on the event loop
through the items/comments seams as the SYSTEM actor. \\Seen is the cursor:
messages are fetched with BODY.PEEK and flagged only after an intake attempt
(a poison message is logged and still flagged — no retry loop).

Spec 62 additions: senders matching no active user become the item's
mail_contact (reporter stays NULL), threaded replies refresh the contact's
last_message_id, plus-addressed recipients (`support+td@…`) route to that
project, and a created-with-contact item is acknowledged by email AFTER the
transaction commits."""

import asyncio
import imaplib
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.exceptions import ConflictError
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.comments import service as comments
from radd.modules.comments.schemas import CommentCreate
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import parsing, service
from .parsing import EmailPlan
from .types import (
    EMAIL_LABEL,
    EMPTY_BODY_PLACEHOLDER,
    NO_SUBJECT_TITLE,
    REPLY_COMMENT_TEMPLATE,
    SEEN_FLAG,
    SENDER_NOTE_TEMPLATE,
    TITLE_MAX_CHARS,
    MailEntity,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AckPlan:
    """An acknowledgment owed to a contact — sent only after the intake commit."""

    email: str
    name: str
    item_key: str
    title: str
    message_id: str


# --- blocking IMAP side (runs via asyncio.to_thread) ---


def _connect() -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(settings.mail_imap_host, settings.mail_imap_port)
    imap.login(settings.mail_imap_username, settings.mail_imap_password)
    imap.select(settings.mail_imap_folder)
    return imap


def fetch_unseen() -> list[tuple[str, bytes]]:
    """(uid, raw message bytes) for every UNSEEN message. BODY.PEEK leaves the
    \\Seen cursor untouched until the intake attempt completes; UIDs are stable
    across connections (unlike sequence numbers)."""
    with _connect() as imap:
        status, data = imap.uid("SEARCH", None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return []
        messages: list[tuple[str, bytes]] = []
        for uid in data[0].split():
            status, fetched = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            if status != "OK":
                continue
            for part in fetched:
                if isinstance(part, tuple) and part[1]:
                    messages.append((uid.decode(), part[1]))
                    break
        return messages


def mark_seen(uids: list[str]) -> None:
    with _connect() as imap:
        for uid in uids:
            imap.uid("STORE", uid, "+FLAGS", SEEN_FLAG)


# --- async intake side ---


async def run_once() -> int:
    messages = await asyncio.to_thread(fetch_unseen)
    if not messages:
        return 0
    processed: list[str] = []
    for uid, raw in messages:
        try:
            plan = parsing.parse_email(raw)
            async with SessionLocal() as session:
                ack = await _intake(session, plan)
                await session.commit()
            if ack is not None:  # post-commit: never ack a rolled-back item
                await service.send_ack(
                    email=ack.email,
                    name=ack.name,
                    item_key=ack.item_key,
                    title=ack.title,
                    message_id=ack.message_id or None,
                )
        except Exception:
            # Flagged \Seen anyway below — a poison message must not wedge the poll.
            logger.exception("mailintake: intake failed for message uid=%s (skipped)", uid)
        processed.append(uid)
    await asyncio.to_thread(mark_seen, processed)
    return len(processed)


def _sender(plan: EmailPlan) -> str:
    if plan.sender_name and plan.sender_email:
        return f"{plan.sender_name} <{plan.sender_email}>"
    return plan.sender_email or plan.sender_name or "(unknown sender)"


async def _sender_user(session: AsyncSession, plan: EmailPlan) -> User | None:
    """The sender resolved to an ACTIVE user — PROVISIONED when unknown
    (RADD-828): a `UserSource.EMAIL` account that cannot log in and whose floor
    is the seeded Requester role (item.read@own + commenting), never the
    Baseline. A later SSO login by the same verified email CLAIMS the account
    instead of forking a duplicate. None only for unparseable senders."""
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


async def _intake(session: AsyncSession, plan: EmailPlan) -> AckPlan | None:
    actor = await auth.get_user(session, SYSTEM_ACTOR_ID)
    body = plan.body or EMPTY_BODY_PLACEHOLDER
    if plan.item_key is not None:
        item = await items.find_item_by_key(session, plan.item_key)
        if item is not None:
            # Reply to an existing thread → public comment; sender noted in the body.
            await comments.create_comment(
                session,
                item.id,
                CommentCreate(body=REPLY_COMMENT_TEMPLATE.format(sender=_sender(plan), body=body)),
                actor,
            )
            await _touch_contact(session, item.id, plan)
            return None
    project = await _target_project(session, plan)
    sender = await _sender_user(session, plan)
    description = body
    if sender is None:
        description = SENDER_NOTE_TEMPLATE.format(body=body, sender=_sender(plan))
    created = await items.create_item(
        session,
        ItemCreate(
            project_id=project.id,
            title=(plan.subject or NO_SUBJECT_TITLE)[:TITLE_MAX_CHARS],
            description=description,
            labels=[EMAIL_LABEL],
            reporter_id=sender.id if sender is not None else None,
        ),
        actor,
    )
    from radd.modules.auth.types import UserSource

    email_sourced = sender is not None and sender.source == UserSource.EMAIL.value
    if (sender is not None and not email_sourced) or not plan.sender_email:
        return None  # staff senders are reporters + auto-watchers, no contact
    # RADD-828: an email-provisioned requester cannot log in — the mail loop
    # (contact row: acks, replies, threading) stays their interface.
    await service.upsert_contact(
        session,
        created.id,
        email=plan.sender_email,
        name=plan.sender_name,
        message_id=plan.message_id or None,
    )
    return AckPlan(
        email=plan.sender_email,
        name=plan.sender_name,
        item_key=created.key,
        title=created.title,
        message_id=plan.message_id,
    )


async def _touch_contact(session: AsyncSession, item_id, plan: EmailPlan) -> None:
    """Threaded reply (spec 62): refresh the existing contact's last_message_id;
    when there is no contact yet and the sender is external, capture them —
    an existing contact's ADDRESS is never overwritten (one contact per item)."""
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


async def _target_project(session: AsyncSession, plan: EmailPlan) -> Project:
    """Plus-address routing (spec 62): a `support+td@…` recipient targets project
    TD when it exists; otherwise (and for untagged mail) RADD_MAIL_PROJECT_KEY."""
    projects = await projects_service.list_projects(session)
    if plan.project_key is not None:
        tagged = next((p for p in projects if p.key == plan.project_key), None)
        if tagged is not None:
            return tagged
    key = settings.mail_project_key.upper()
    if not key:
        raise ConflictError(MailEntity.MAIL, reason="RADD_MAIL_PROJECT_KEY is unset")
    project = next((p for p in projects if p.key == key), None)
    if project is None:
        raise ConflictError(MailEntity.MAIL, reason=f"no project with key {key}")
    return project
