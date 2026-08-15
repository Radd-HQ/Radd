"""RADD-1085 — what leaves the building is gated on field grants.

Event payloads deliberately carry the FULL item for in-process consumers; a
webhook endpoint can hold no grant and sit in no team, so restricted values
must be redacted at the delivery seam, and the search headline must not read
out a description the item API would blank.

Grant rows here are FLUSHED, never committed: a committed read grant would
gate snippets instance-wide for every later test in the run (the exact
cross-test pollution RADD-845's first cut demonstrated).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.access.models import AccessGrant
from radd.modules.fields import service as fields_service
from radd.modules.fields.models import FieldDefinition
from radd.modules.items.redaction import redact_item_payload
from radd.modules.webhooks.service import _outbound_payload


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


# --- the pure redactor -------------------------------------------------------


def _item_payload() -> dict:
    return {
        "item": {
            "key": "SKY-1",
            "title": "public title",
            "description": "the secret plan",
            "assignee": {"id": "u1", "name": "Maya"},
            "labels": ["a"],
            "custom_fields": {"salary_band": "L7", "component": "API"},
        },
        "changes": [
            {"field": "title", "from": "a", "to": "b"},
            {"field": "assignee", "from": None, "to": "Maya"},
            {"field": "custom_field", "key": "salary_band", "from": "L6", "to": "L7"},
            {"field": "custom_field", "key": "component", "from": None, "to": "API"},
        ],
    }


def test_redaction_strips_restricted_and_keeps_the_rest():
    payload = _item_payload()
    out = redact_item_payload(
        payload, custom_keys=frozenset({"salary_band"}), builtin_names=frozenset({"assignee", "description"})
    )
    item = out["item"]
    assert item["custom_fields"] == {"component": "API"}
    assert item["assignee"] is None
    assert item["description"] == ""  # the same blank shape the API serves
    assert item["title"] == "public title"  # title is never restrictable
    # the diff would leak both values — entries for restricted fields drop
    assert [c["field"] for c in out["changes"]] == ["title", "custom_field"]
    assert out["changes"][1]["key"] == "component"


def test_redaction_is_copy_on_write():
    """The input is the events row's JSONB — mutating it would rewrite history."""
    payload = _item_payload()
    redact_item_payload(payload, frozenset({"salary_band"}), frozenset({"assignee"}))
    assert payload["item"]["custom_fields"] == {"salary_band": "L7", "component": "API"}
    assert payload["item"]["assignee"] == {"id": "u1", "name": "Maya"}
    assert len(payload["changes"]) == 4


def test_no_restrictions_means_the_original_object():
    payload = _item_payload()
    assert redact_item_payload(payload, frozenset(), frozenset()) is payload


def test_internal_comment_excerpt_is_withheld_from_endpoints():
    payload = {"visibility": "internal", "excerpt": "team-only words", "author": {"name": "A"}}
    out = _outbound_payload(payload, (frozenset(), frozenset()))
    assert out["excerpt"] is None
    assert payload["excerpt"] == "team-only words"  # copy-on-write here too
    public = {"visibility": "public", "excerpt": "fine"}
    assert _outbound_payload(public, (frozenset(), frozenset()))["excerpt"] == "fine"


# --- the fail-closed grant resolution -----------------------------------------


async def test_outbound_restricted_keys_reflect_real_grants(db):
    """A READ grant anywhere restricts the key for grant-less consumers; a
    WRITE-only grant does not (write rules are spec 36's concern, not read
    leakage). Real rows, real resolution — no mocks (the vacuous-pass rules)."""
    definition = FieldDefinition(
        id=uuid.uuid4(),
        key=f"redact_{uuid.uuid4().hex[:6]}",
        name="Redaction probe",
        type="text",
        source="user",
    )
    db.add(definition)
    await db.flush()

    before_custom, before_builtin = await fields_service.outbound_restricted_keys(db)
    assert definition.key not in before_custom

    db.add(
        AccessGrant(
            resource_type=fields_service.FIELD_RESOURCE,
            resource_id=str(definition.id),
            subject_type="user",
            subject_id=uuid.uuid4(),
            access="read",
        )
    )
    db.add(
        AccessGrant(
            resource_type=fields_service.BUILTIN_RESOURCE,
            resource_id="description",
            subject_type="user",
            subject_id=uuid.uuid4(),
            access="read",
        )
    )
    # write-only grant on another builtin must NOT mark it read-restricted
    db.add(
        AccessGrant(
            resource_type=fields_service.BUILTIN_RESOURCE,
            resource_id="assignee",
            subject_type="user",
            subject_id=uuid.uuid4(),
            access="write",
        )
    )
    await db.flush()

    custom, builtins = await fields_service.outbound_restricted_keys(db)
    assert definition.key in custom
    assert "description" in builtins
    assert "assignee" not in builtins
