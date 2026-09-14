"""The mail channel's own events (RADD-960).

Before these, `mailintake` emitted nothing: automations could see the ITEM intake
created and the COMMENT it appended, but never that the cause was email. A rule
could not tell a customer's reply from an agent typing in the UI.

Two things are pinned here and they pull in opposite directions. The events must
CARRY enough for a rule to be worth writing (who sent it, from what domain, did it
open the ticket or land on one) — and must NOT carry the body, because an event
payload is readable by anything that can read the stream while the body already
lives on the item behind the item's own read gate.
"""

import uuid
from email.message import EmailMessage

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.events.models import Event
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.mailintake import intake, parsing, threading
from radd.modules.mailintake.types import MailDirection, MailEvent
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

BODY = "the customer's confidential sentence"


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def world(db):
    suffix = uuid.uuid4().hex[:8]
    actor = User(
        email=f"me-{suffix}@example.com", name="Mail", instance_role=InstanceRole.ADMIN.value
    )
    db.add(actor)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"ME{suffix[:4].upper()}", name="Mail events")
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Existing"), actor
    )
    return actor, project, item


def raw(*, subject="Hello", sender="Jane <jane@vip-customer.com>", message_id, **headers) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = "help@radd-hq.com"
    message["Message-ID"] = message_id
    for key, value in headers.items():
        message[key.replace("_", "-")] = value
    message.set_content(BODY)
    return message.as_bytes()


async def _accept(db, blob: bytes, project_key: str):
    return await intake.accept(
        db,
        parsing.parse_email(blob),
        raw=blob,
        default_project_key=project_key,
        own_addresses={"agent@radd-hq.com"},
    )


async def _events(db, event_type: MailEvent) -> list[Event]:
    rows = await db.execute(select(Event).where(Event.event_type == event_type.value))
    return list(rows.scalars())


async def test_a_new_ticket_from_mail_emits_received_saying_it_created_one(db, world):
    _, project, _ = world
    before = len(await _events(db, MailEvent.RECEIVED))
    outcome = await _accept(db, raw(message_id="<new@ext>"), project.key)

    rows = await _events(db, MailEvent.RECEIVED)
    assert len(rows) == before + 1
    payload = rows[-1].payload
    assert payload["created_item"] is True
    assert payload["sender"] == "jane@vip-customer.com"
    # The condition people actually write is "from a VIP domain" — derived once
    # here rather than by every rule author.
    assert payload["sender_domain"] == "vip-customer.com"
    assert outcome.result is intake.Result.CREATED


async def test_a_reply_emits_received_saying_it_did_not_create_one(db, world):
    """The distinction the whole feature turns on: "reopen when the customer
    replies" must not fire on the message that opened the ticket."""
    _, project, item = world
    await threading.record(
        db, message_id="<sent@radd>", item_id=item.id, direction=MailDirection.OUTBOUND
    )
    await _accept(db, raw(message_id="<reply@ext>", In_Reply_To="<sent@radd>"), project.key)

    payload = (await _events(db, MailEvent.RECEIVED))[-1].payload
    assert payload["created_item"] is False


async def test_received_is_item_scoped_so_item_actions_apply(db, world):
    """`item_scoped` is what makes SLQ conditions and item actions work on the
    ticket; without the subject ref a rule resolves no target and does nothing."""
    _, project, _ = world
    outcome = await _accept(db, raw(message_id="<scoped@ext>"), project.key)
    row = (await _events(db, MailEvent.RECEIVED))[-1]
    assert row.payload["item"]["id"] == str(outcome.item_id)


async def test_no_mail_event_carries_the_message_body(db, world):
    """An event payload is readable by anything that can read the stream. The
    body already lives on the item behind the item's own read gate, and copying
    it here would quietly widen who can see it with no screen admitting that."""
    _, project, _ = world
    await _accept(db, raw(message_id="<secret@ext>"), project.key)
    await _accept(
        db, raw(message_id="<dropped@ext>", Auto_Submitted="auto-replied"), project.key
    )
    for event_type in (MailEvent.RECEIVED, MailEvent.DROPPED):
        for row in await _events(db, event_type):
            assert BODY not in str(row.payload)


async def test_a_dropped_message_emits_the_reason(db, world):
    """A silent drop and a bug are indistinguishable from outside, and a log line
    is not queryable."""
    _, project, _ = world
    before = len(await _events(db, MailEvent.DROPPED))
    outcome = await _accept(
        db, raw(message_id="<auto@ext>", Auto_Submitted="auto-replied"), project.key
    )
    assert outcome.result is intake.Result.IGNORED
    rows = await _events(db, MailEvent.DROPPED)
    assert len(rows) == before + 1
    assert "auto-replied" in rows[-1].payload["reason"]


def test_dropped_entity_id_is_correlatable_by_message_id():
    """RADD-1035c. `entity_id=uuid.uuid4()` scattered every drop across a fresh
    id, so a provider retrying a message the loop guard keeps rejecting looked
    like N unrelated drops. It is now uuid5 over the Message-ID — same message,
    one id — falling back to uuid4 only when there is nothing to correlate on."""
    a = intake.dropped_entity_id("<m@x>")
    assert a == intake.dropped_entity_id("<m@x>")
    assert a != intake.dropped_entity_id("<other@x>")
    assert intake.dropped_entity_id("") != intake.dropped_entity_id("")


async def test_a_loop_drop_keys_its_event_off_the_message_id(db, world):
    """The event a repeated loop drop writes carries the correlatable id, so an
    operator can group every rejection of the SAME message."""
    _, project, _ = world
    await _accept(
        db, raw(message_id="<loopdrop@ext>", Auto_Submitted="auto-replied"), project.key
    )
    rows = await _events(db, MailEvent.DROPPED)
    assert any(r.entity_id == intake.dropped_entity_id("<loopdrop@ext>") for r in rows)


def test_every_mail_event_is_a_registered_automation_trigger():
    """`catalog.TRIGGERS` derives live from the kernel event registry, so this is
    what makes them appear in the rule builder — with no edit to `automations`.
    Asserted rather than assumed: a manifest that forgets one produces an event
    nobody can ever write a rule against, and nothing fails."""
    from radd.kernel import registries
    from radd.modules.automations import catalog

    triggers = catalog.TRIGGERS
    for event in MailEvent:
        # Spec 123: the configuration events (mail_source.*, mail_sender.*,
        # mail_rule.*) are registered for the audit log but deliberately NOT
        # triggers — a rule that fires on its own mailbox being edited is noise.
        assert event.value in registries.event_types, f"{event.value} is not registered"
        if event.value.startswith("mail."):
            assert event.value in triggers, f"{event.value} is not a trigger"
        else:
            assert event.value not in triggers, f"{event.value} should not be a trigger"
    assert triggers[MailEvent.RECEIVED.value].item_scoped is True
    # No item exists for a dropped message, by definition.
    assert triggers[MailEvent.DROPPED.value].item_scoped is False
