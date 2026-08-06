"""Notify planning core (spec 26).

Pure, DB-free tests of the invariants everything else leans on: the actor is
never self-notified, one notification per user per event with personal types
(assigned/mentioned) beating ambient ones (state_changed/commented), auto-watch
sets, and the mention grammar. The full consumer (permission filtering, mention
resolution, email digests) is exercised against a live DB by the demo flows.
"""

import uuid

from radd.modules.notify import planner
from radd.modules.notify.types import NotificationType

ACTOR = uuid.uuid4()
ASSIGNEE = uuid.uuid4()
WATCHER = uuid.uuid4()
MENTIONED = uuid.uuid4()
REPORTER = uuid.uuid4()


def _types_by_user(plan: planner.Plan) -> dict[uuid.UUID, NotificationType]:
    return {p.user_id: p.type for p in plan.notifications}


# --- mention grammar ---


def test_parse_mentions_token_and_email_forms():
    user_id = uuid.uuid4()
    ids, emails = planner.parse_mention_candidates(
        f"Ping @[Jane Doe]({user_id}) and @jane@example.com about this."
    )
    assert ids == {str(user_id)}
    assert emails == {"jane@example.com"}


def test_parse_mentions_empty_and_plain_text():
    assert planner.parse_mention_candidates("") == (set(), set())
    # A bare email without the @ prefix is not a mention.
    assert planner.parse_mention_candidates("mail jane@example.com please") == (set(), set())


# --- item created ---


def test_create_assigns_and_watches():
    payload = {"item": {"assignee": {"id": str(ASSIGNEE), "name": "A"}}}
    plan = planner.plan_item_created(payload, ACTOR, frozenset())
    assert plan.watch == {ACTOR, ASSIGNEE}
    assert _types_by_user(plan) == {ASSIGNEE: NotificationType.ASSIGNED}


def test_create_never_notifies_the_actor():
    # Self-assignment on create: watch yes, notification no.
    payload = {"item": {"assignee": {"id": str(ACTOR), "name": "A"}}}
    plan = planner.plan_item_created(payload, ACTOR, frozenset({ACTOR}))
    assert plan.watch == {ACTOR}
    assert plan.notifications == []


def test_create_mentions_notify():
    plan = planner.plan_item_created({"item": {"assignee": None}}, ACTOR, frozenset({MENTIONED}))
    assert _types_by_user(plan) == {MENTIONED: NotificationType.MENTIONED}


# --- item updated ---


def test_update_state_change_notifies_watchers_not_actor():
    payload = {
        "assignee": None,
        "changes": [{"field": "state", "from": "Todo", "to": "Done"}],
    }
    plan = planner.plan_item_updated(payload, ACTOR, frozenset({WATCHER, ACTOR}), frozenset())
    assert _types_by_user(plan) == {WATCHER: NotificationType.STATE_CHANGED}
    assert plan.notifications[0].detail == {"from": "Todo", "to": "Done"}


def test_update_assignment_beats_state_change():
    # New assignee also watches: one ASSIGNED notification, not two.
    payload = {
        "item": {"assignee": {"id": str(ASSIGNEE), "name": "A"}},
        "changes": [
            {"field": "assignee", "from": None, "to": "A"},
            {"field": "state", "from": "Todo", "to": "Doing"},
        ],
    }
    plan = planner.plan_item_updated(payload, ACTOR, frozenset({ASSIGNEE, WATCHER}), frozenset())
    assert _types_by_user(plan) == {
        ASSIGNEE: NotificationType.ASSIGNED,
        WATCHER: NotificationType.STATE_CHANGED,
    }


def test_update_without_relevant_changes_plans_nothing():
    payload = {"item": {"assignee": None}, "changes": [{"field": "title", "from": "a", "to": "b"}]}
    plan = planner.plan_item_updated(payload, ACTOR, frozenset({WATCHER}), frozenset())
    assert plan.notifications == [] and plan.watch == set()


# --- reporter auto-watch (spec 62) ---


def test_create_reporter_auto_watches_without_a_ping():
    payload = {"item": {"assignee": None, "reporter": {"id": str(REPORTER), "name": "R"}}}
    plan = planner.plan_item_created(payload, ACTOR, frozenset())
    assert plan.watch == {ACTOR, REPORTER}
    assert plan.notifications == []  # watching, not a notification


def test_create_without_reporter_watches_only_the_actor():
    plan = planner.plan_item_created({"item": {"assignee": None, "reporter": None}}, ACTOR, frozenset())
    assert plan.watch == {ACTOR}


def test_update_reporter_change_watches_the_new_reporter():
    payload = {
        "item": {"assignee": None, "reporter": {"id": str(REPORTER), "name": "R"}},
        "changes": [{"field": "reporter", "from": None, "to": "R"}],
    }
    plan = planner.plan_item_updated(payload, ACTOR, frozenset(), frozenset())
    assert plan.watch == {REPORTER}
    assert plan.notifications == []


def test_update_untouched_reporter_is_not_rewatched():
    # The snapshot always carries the reporter; only a `reporter` CHANGE watches
    # them (an unwatch must stick when unrelated fields move).
    payload = {
        "item": {"assignee": None, "reporter": {"id": str(REPORTER), "name": "R"}},
        "changes": [{"field": "title", "from": "a", "to": "b"}],
    }
    plan = planner.plan_item_updated(payload, ACTOR, frozenset(), frozenset())
    assert plan.watch == set()


# --- comment created ---


def test_comment_notifies_watchers_and_mentions_win():
    payload = {"excerpt": "hey", "visibility": "public"}
    plan = planner.plan_comment_created(
        payload, ACTOR, frozenset({WATCHER, MENTIONED, ACTOR}), frozenset({MENTIONED})
    )
    assert plan.watch == {ACTOR}  # author auto-watches
    assert _types_by_user(plan) == {
        MENTIONED: NotificationType.MENTIONED,
        WATCHER: NotificationType.COMMENTED,
    }


def test_comment_carries_visibility_for_internal_filtering():
    # The consumer drops internal-comment recipients without comment.read_internal;
    # the planner must thread visibility through for that check.
    payload = {"excerpt": "secret", "visibility": "internal"}
    plan = planner.plan_comment_created(payload, ACTOR, frozenset({WATCHER}), frozenset())
    assert plan.notifications[0].detail["visibility"] == "internal"
