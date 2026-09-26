"""The CSAT sender (spec 65): an outbox consumer that emails a one-click survey
when an `item.updated` moves an item into a done-category state.

Head-seeded cursor (`events.runner.run_head_seeded`): first start never surveys
the backlog; cursor, survey row and `csat.requested` commit BEFORE any mail
leaves — at-most-once, a dropped survey beats a duplicate. With mail or the
project's CSAT_ENABLED off, events are skipped and the cursor still advances.

Guards, in order: moved into done; CSAT_ENABLED; a mail sender exists; no
survey yet (one per item lifetime); a recipient resolves (mail contact, else a
mailable reporter). Sent through `mailintake.send_item_mail` with
`pin_subject=True`: its own subject, but still threaded onto the ticket.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.auth import service as auth_service
from radd.modules.events import runner
from radd.modules.events.service import Event
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEvent
from radd.modules.items.models import WorkItem
from radd.modules.mailintake import service as mail_service
from radd.modules.mailintake.types import SentMailKind
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey
from radd.modules.workflow.types import StateCategory

from . import service
from .types import (
    CONSUMER_NAME,
    RATING_LABELS,
    RATING_LINK_TEMPLATE,
    STATE_CHANGE_FIELD,
    SURVEY_BODY_TEMPLATE,
    SURVEY_SUBJECT_TEMPLATE,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SurveyEmail:
    #: The item being surveyed — the transport threads and resolves its sender
    #: on it, so it travels with the plan rather than being looked up again.
    item_id: uuid.UUID
    email: str
    name: str
    subject: str
    body: str


def moved_to_done(payload: dict) -> bool:
    """Pure resolve detection: the diff touched `state` AND the payload's state
    embed (the NEW state — item.updated snapshots are post-mutation) is in the
    done category. A done→done rename-move also passes, harmlessly — the unique
    survey row keeps everything once-only."""
    changes = payload.get("changes") or []
    if not any(change.get("field") == STATE_CHANGE_FIELD for change in changes):
        return False
    state = ((payload.get("item") or {}).get("state")) or {}
    return state.get("category") == StateCategory.DONE.value


def survey_body(*, key: str, title: str, token: str) -> str:
    links = "\n".join(
        RATING_LINK_TEMPLATE.format(
            label=RATING_LABELS[rating],
            base_url=settings.app_base_url,
            token=token,
            rating=rating,
        )
        for rating in sorted(RATING_LABELS)
    )
    return SURVEY_BODY_TEMPLATE.format(key=key, title=title, links=links)


async def resolve_recipient(session: AsyncSession, item: WorkItem) -> tuple[str, str] | None:
    """(email, name): the item's mail contact, else the reporter if
    `mail_service.mailable_user` — `active` alone passes service accounts and
    the system actor, which have no mailbox (RADD-983)."""
    contact = await mail_service.contact_for_item(session, item.id)
    if contact is not None:
        return contact.email, contact.name
    if item.reporter_id is None:
        return None
    reporter = (await auth_service.users_by_ids(session, [item.reporter_id])).get(
        item.reporter_id
    )
    if not mail_service.mailable_user(reporter):
        return None
    return reporter.email, reporter.name


async def process_event(session: AsyncSession, event: Event) -> SurveyEmail | None:
    """Apply the guards to one item.updated event. On a pass, create the survey
    row + emit csat.requested (the caller commits them with the cursor) and
    return the planned email for post-commit delivery."""
    payload = event.payload or {}
    if not moved_to_done(payload):
        return None
    item_id = uuid.UUID(event.entity_id)
    try:
        item = await items_service.require_item(session, item_id)
    except NotFoundError:
        return None  # deleted since the event
    enabled = await settings_service.resolve(
        session, SettingKey.CSAT_ENABLED, project_id=item.project_id
    )
    if not enabled:
        return None  # per-project opt-in — dev projects never send surveys
    if not await mail_service.outbound_configured(session):
        # Logged: a silent skip here made "no surveys" unreportable (RADD-983).
        logger.info(
            "csat: survey for %s skipped — no mail sender is configured", item_id
        )
        return None
    if await service.survey_for_item(session, item_id) is not None:
        return None  # one survey per item lifetime
    recipient = await resolve_recipient(session, item)
    if recipient is None:
        return None
    item_ref = payload.get("item") or {}
    key = item_ref.get("key") or str(item_id)
    title = item_ref.get("title") or ""
    survey = await service.create_survey(session, item_id=item_id)
    email, name = recipient
    return SurveyEmail(
        item_id=item_id,
        email=email,
        name=name,
        subject=SURVEY_SUBJECT_TEMPLATE.format(key=key),
        body=survey_body(key=key, title=title, token=survey.token),
    )


async def _plan(session: AsyncSession, event: Event) -> SurveyEmail | None:
    if event.event_type != ItemEvent.UPDATED.value:
        return None
    return await process_event(session, event)


async def _deliver_all(emails: list[SurveyEmail]) -> None:
    for email in emails:
        await _deliver(email)


async def run_once() -> int:
    return await runner.run_head_seeded(
        CONSUMER_NAME, batch_size=settings.csat_batch, plan=_plan, deliver=_deliver_all
    )


async def _deliver(email: SurveyEmail, session: AsyncSession | None = None) -> None:
    """Post-commit delivery through mailintake's transport. Never raises and never
    retries: a survey is a nicety; a failure is a `mail.failed` event and a log.
    Production passes no session (everything is committed); a test passes its own."""
    sent = await mail_service.send_item_mail(
        session,
        item_id=email.item_id,
        to_address=email.email,
        to_name=email.name,
        subject=email.subject,
        text=email.body,
        pin_subject=True,
        kind=SentMailKind.SURVEY,
    )
    if sent is None:
        logger.warning("csat: survey to %s was not sent", email.email)
