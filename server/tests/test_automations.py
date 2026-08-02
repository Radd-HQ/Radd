"""Automations match/apply core (spec 15).

Pure, DB-free tests of the pieces many things depend on: the loop guard (the engine
must never react to its own effects), the trigger mapping, action-union validation, and
the read-only action planner's resolution/clear semantics. The full async engine — SLQ
matching against a live item, applying via the services, and the loop guard holding
end-to-end — is exercised by scripts/demo_automations.sh on an isolated database.
"""

import uuid

import pytest
from pydantic import ValidationError

from radd.modules.automations import catalog, engine
from radd.modules.automations.engine import (
    _is_clear,
    _plan,
    condition_matches,
    is_automation_caused,
    should_process,
)
from radd.modules.automations.schemas import RuleCreate
from radd.modules.automations.types import (
    CLEAR_VALUE,
    MANUAL_TRIGGER,
    SYSTEM_ACTOR_ID,
    ActionType,
)
from radd.modules.items.enums import ItemEvent, Priority


class StubEvent:
    """Duck-types events.models.Event for the classification predicates."""

    def __init__(self, event_type: str, actor_id: uuid.UUID | None, silent: bool = False):
        self.event_type = event_type
        self.actor_id = actor_id
        self.silent = silent


# --- loop guard (the critical invariant) ---


def test_automation_caused_is_the_system_actor():
    assert is_automation_caused(StubEvent(ItemEvent.UPDATED.value, SYSTEM_ACTOR_ID)) is True
    assert is_automation_caused(StubEvent(ItemEvent.UPDATED.value, uuid.uuid4())) is False
    assert is_automation_caused(StubEvent(ItemEvent.UPDATED.value, None)) is False


def test_should_process_skips_automation_caused_events():
    # A human update is processed; the engine's own item.updated (system actor) is NOT —
    # this is what stops a rule keyed on its own effect from spinning.
    assert should_process(StubEvent(ItemEvent.UPDATED.value, uuid.uuid4())) is True
    assert should_process(StubEvent(ItemEvent.CREATED.value, uuid.uuid4())) is True
    assert should_process(StubEvent(ItemEvent.UPDATED.value, SYSTEM_ACTOR_ID)) is False


def test_should_process_skips_silent_bulk_import_events():
    # Spec 100: a rule that assigns on create or transitions on a field change must
    # not fire once per imported issue and rewrite the history being imported.
    assert should_process(StubEvent(ItemEvent.CREATED.value, uuid.uuid4(), silent=True)) is False
    assert should_process(StubEvent("comment.created", uuid.uuid4(), silent=True)) is False


def test_should_process_covers_the_catalog_and_nothing_else():
    # Spec 58: any catalog trigger is subscribable — comment/worklog/cycle events
    # now fire rules. Config-noise events stay out (they're not in the catalog).
    assert should_process(StubEvent("comment.created", uuid.uuid4())) is True
    assert should_process(StubEvent("worklog.created", uuid.uuid4())) is True
    assert should_process(StubEvent("cycle.completed", uuid.uuid4())) is True
    assert should_process(StubEvent("automation.created", uuid.uuid4())) is False
    assert should_process(StubEvent("notification.created", uuid.uuid4())) is False
    assert should_process(StubEvent("no.such.event", uuid.uuid4())) is False


# --- trigger catalog invariants ---


def test_catalog_is_sane():
    # MANUAL is deliberately NOT in the catalog: manual rules only run on demand via
    # POST /automations/{id}/run — the event engine must never fire them.
    assert MANUAL_TRIGGER not in catalog.TRIGGERS
    assert catalog.TRIGGERS[ItemEvent.UPDATED.value].has_changes is True
    assert catalog.TRIGGERS[ItemEvent.UPDATED.value].item_scoped is True
    assert catalog.TRIGGERS["comment.created"].item_scoped is True
    assert catalog.TRIGGERS["cycle.completed"].item_scoped is False
    # every key is the spec's own event_type (dict built from the specs)
    assert all(key == spec.event_type for key, spec in catalog.TRIGGERS.items())


# --- action-union validation (validated on rule write) ---


def _rule(actions: list[dict]) -> RuleCreate:
    return RuleCreate.model_validate(
        {
            "name": "r",
            "trigger": "item.created",
            "actions": actions,
        }
    )


def test_action_union_accepts_each_type():
    rule = _rule(
        [
            {"type": "set_state", "params": {"state": "In Review"}},
            {"type": "set_priority", "params": {"priority": "high"}},
            {"type": "add_label", "params": {"label": "urgent"}},
            {"type": "set_custom_field", "params": {"key": "risk", "value": 3}},
            {"type": "add_comment", "params": {"body": "hi", "visibility": "internal"}},
        ]
    )
    assert [a.type for a in rule.actions] == [
        ActionType.SET_STATE,
        ActionType.SET_PRIORITY,
        ActionType.ADD_LABEL,
        ActionType.SET_CUSTOM_FIELD,
        ActionType.ADD_COMMENT,
    ]


def test_action_union_rejects_unknown_type():
    with pytest.raises(ValidationError):
        _rule([{"type": "delete_item", "params": {}}])


def test_action_union_rejects_bad_params():
    with pytest.raises(ValidationError):
        _rule([{"type": "set_priority", "params": {"priority": "urgent"}}])  # not a Priority
    with pytest.raises(ValidationError):
        _rule([{"type": "set_state", "params": {}}])  # missing state name


def test_rule_requires_at_least_one_action():
    with pytest.raises(ValidationError):
        _rule([])


# --- clear sentinel + read-only planner (no session for these branches) ---


def test_clear_value_sentinel():
    assert _is_clear(CLEAR_VALUE) and _is_clear("NONE") and _is_clear("  none ")
    assert not _is_clear("someone@example.com")


async def test_empty_condition_always_matches():
    # Empty (default '') means "always" — returns True without touching the session.
    assert await condition_matches(None, "", item=None, project=None) is True
    assert await condition_matches(None, "   ", item=None, project=None) is True


def _plan_kwargs() -> dict:
    return {
        "facts": engine._manual_facts(),
        "rule_name": "r",
    }


async def test_plan_set_priority_is_pure_and_typed():
    plan = await _plan(
        None,
        {"type": "set_priority", "params": {"priority": "blocker"}},
        None,
        None,
        None,
        **_plan_kwargs(),
    )
    assert plan.kind == "item_update"
    assert plan.item_update.priority is Priority.BLOCKER


async def test_plan_clear_actions_mark_the_field_set_to_null():
    # An explicit clear must set the field in model_fields_set so update_item nulls it
    # (omitted = unchanged, explicit null = clear — the ItemUpdate contract).
    plan = await _plan(
        None, {"type": "set_assignee", "params": {"assignee": "none"}}, None, None, None,
        **_plan_kwargs(),
    )
    assert plan.item_update.assignee_id is None
    assert "assignee_id" in plan.item_update.model_fields_set

    plan = await _plan(
        None, {"type": "set_team", "params": {"team": "None"}}, None, None, None, **_plan_kwargs()
    )
    assert "team_id" in plan.item_update.model_fields_set


async def test_plan_set_custom_field_and_comment():
    plan = await _plan(
        None, {"type": "set_custom_field", "params": {"key": "risk", "value": 5}}, None, None, None,
        **_plan_kwargs(),
    )
    assert plan.item_update.custom_fields == {"risk": 5}

    plan = await _plan(
        None, {"type": "add_comment", "params": {"body": "auto", "visibility": "public"}},
        None, None, None, **_plan_kwargs(),
    )
    assert plan.kind == "comment" and plan.comment.body == "auto"


# --- universal actions (spec 58b) — pure plan branches ---


async def test_plan_post_chat_renders_the_template():
    from radd.modules.automations.conditions import EventFacts

    facts = EventFacts(
        event_type="cycle.completed",
        actor_id=None,
        actor_email="hussein@hjarrar.com",
        actor_name="Hussein Jarrar",
        payload={"name": "PIPE - 115"},
    )
    plan = await _plan(
        None,
        {
            "type": "post_chat",
            "params": {
                "webhook_url": "https://chat.example/hook",
                "message": "Cycle {{payload.name}} completed by {{actor.name}} ({{missing}})",
            },
        },
        None,
        None,
        None,
        facts=facts,
        rule_name="r",
    )
    assert plan.kind == "http"
    url, body, secret = plan.http
    assert body == {"text": "Cycle PIPE - 115 completed by Hussein Jarrar ({{missing}})"}
    assert secret == ""


async def test_plan_send_webhook_carries_event_and_rule():
    facts = engine._manual_facts()
    plan = await _plan(
        None,
        {"type": "send_webhook", "params": {"url": "https://x.example/h", "secret": "s3cr3t"}},
        None,
        None,
        None,
        facts=facts,
        rule_name="my rule",
    )
    url, body, secret = plan.http
    assert (url, secret) == ("https://x.example/h", "s3cr3t")
    assert body["rule"] == "my rule" and body["event_type"] == "manual"


def test_action_union_accepts_universal_actions():
    rule = _rule(
        [
            {"type": "create_item", "params": {"project": "TD", "title": "Retro for {{payload.name}}"}},
            {"type": "send_webhook", "params": {"url": "https://x.example/h"}},
            {"type": "post_chat", "params": {"webhook_url": "https://chat.example/h", "message": "m"}},
            {"type": "notify_user", "params": {"user": "a@b.c", "message": "m"}},
        ]
    )
    assert [a.type for a in rule.actions] == [
        ActionType.CREATE_ITEM,
        ActionType.SEND_WEBHOOK,
        ActionType.POST_CHAT,
        ActionType.NOTIFY_USER,
    ]
    # non-http URL rejected
    with pytest.raises(ValidationError):
        _rule([{"type": "send_webhook", "params": {"url": "ftp://nope"}}])


def test_item_actions_registry_covers_exactly_the_item_bound_types():
    from radd.modules.automations.types import ITEM_ACTIONS

    universal = {
        ActionType.CREATE_ITEM,
        ActionType.SEND_WEBHOOK,
        ActionType.POST_CHAT,
        ActionType.NOTIFY_USER,
        ActionType.SEND_EMAIL,  # spec 66
    }
    assert ITEM_ACTIONS == set(ActionType) - universal


def test_system_actor_id_is_stable():
    # The loop-guard marker must equal the id the migration seeds; changing it would
    # both orphan the seeded user and silently break the guard.
    assert str(SYSTEM_ACTOR_ID) == "00000000-0000-0000-0000-000000a70a70"
    assert engine.SYSTEM_ACTOR_ID == SYSTEM_ACTOR_ID
