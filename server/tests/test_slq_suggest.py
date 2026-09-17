"""SLQ suggest tests (spec 12): context detection at every position class (incl.
mid-token, inside quotes, inside IN lists, after ORDER BY), op-tables per field
type, ranking, quoting of spacey values, scope narrowing, and the response cap.

Detection and assembly are pure (session=None like test_slq); value sources run
against live Postgres inside a rolled-back transaction, so nothing persists.
"""

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.fields.models import FieldDefinition
from radd.modules.fields.types import FieldType
from radd.modules.items.enums import ItemKind, Priority
from radd.modules.items.models import WorkItem
from radd.modules.items.slq.suggest import SuggestResponse, suggest, suggestions_for
from radd.modules.items.slq.suggest_context import (
    KeywordSuggestion,
    Offer,
    SuggestContext,
    detect,
)
from radd.modules.items.slq.suggest_values import DATE_TEMPLATE, MAX_SUGGESTIONS, SuggestScope
from radd.modules.labels import service as labels_service
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate
from radd.modules.workflow import service as workflow
from radd.modules.workflow.schemas import StateCreate
from radd.modules.workflow.types import StateCategory
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project
from radd.modules.projects.schemas import ProjectCreate


def cf(key: str, field_type: FieldType, options: list[str] | None = None) -> FieldDefinition:
    return FieldDefinition(
        id=uuid.uuid4(),
        key=key,
        name=key.capitalize(),
        type=field_type.value,
        options=options,
        source="user",
    )


DEFS = {
    d.key: d
    for d in (
        cf("notes", FieldType.TEXT),
        cf("homepage", FieldType.URL),
        cf("reviewer", FieldType.USER),
        cf("show", FieldType.SELECT, ["RUX", "BNX", "Main Show", "none"]),
        cf("software", FieldType.MULTI_SELECT, ["Maya", "Houdini"]),
        cf("budget", FieldType.NUMBER),
        cf("spent", FieldType.DURATION),
        cf("due", FieldType.DATE),
        cf("billable", FieldType.BOOLEAN),
    )
}


async def respond(
    q: str,
    cursor: int | None = None,
    session: AsyncSession | None = None,
    scope: SuggestScope | None = None,
    defs: dict[str, FieldDefinition] | None = None,
) -> SuggestResponse:
    return await suggestions_for(
        session,
        q=q,
        cursor=cursor,
        scope=scope or SuggestScope(),
        definitions_by_key=DEFS if defs is None else defs,
    )


def values(response: SuggestResponse) -> list[str]:
    return [s.value for s in response.suggestions]


def by_value(response: SuggestResponse) -> dict[str, str]:
    return {s.value: s.insert for s in response.suggestions}


# --- context detection: every position class ---


@pytest.mark.parametrize(
    ("q", "context", "offer", "replace_from", "partial"),
    [
        # start / after AND, OR, NOT, '(' -> field
        ("", SuggestContext.FIELD, Offer.FIELDS, 0, ""),
        ("sta", SuggestContext.FIELD, Offer.FIELDS, 0, "sta"),
        ("state", SuggestContext.FIELD, Offer.FIELDS, 0, "state"),
        ("state = Done AND ", SuggestContext.FIELD, Offer.FIELDS, 17, ""),
        ("state = Done AND pri", SuggestContext.FIELD, Offer.FIELDS, 17, "pri"),
        ("state = Done OR ", SuggestContext.FIELD, Offer.FIELDS, 16, ""),
        ("NOT ", SuggestContext.FIELD, Offer.FIELDS, 4, ""),
        ("(", SuggestContext.FIELD, Offer.FIELDS, 1, ""),
        ("state = Done AND (", SuggestContext.FIELD, Offer.FIELDS, 18, ""),
        # after a field -> operator (incl. partial/unlexable operator tails)
        ("state ", SuggestContext.OPERATOR, Offer.OPERATORS, 6, ""),
        ("state !", SuggestContext.OPERATOR, Offer.OPERATORS, 6, "!"),
        ("state I", SuggestContext.OPERATOR, Offer.OPERATORS, 6, "I"),
        ("state IN", SuggestContext.OPERATOR, Offer.OPERATORS, 6, "IN"),
        ("assignee IS ", SuggestContext.OPERATOR, Offer.KEYWORDS, 12, ""),
        ("assignee IS NOT ", SuggestContext.OPERATOR, Offer.KEYWORDS, 16, ""),
        ("assignee IS NOT EM", SuggestContext.OPERATOR, Offer.KEYWORDS, 16, "EM"),
        ("team NOT ", SuggestContext.OPERATOR, Offer.KEYWORDS, 9, ""),
        # after an operator / inside IN lists -> value
        ("state = ", SuggestContext.VALUE, Offer.VALUES, 8, ""),
        ("state = Do", SuggestContext.VALUE, Offer.VALUES, 8, "Do"),
        ("number >= ", SuggestContext.VALUE, Offer.VALUES, 10, ""),
        ("state IN ", SuggestContext.VALUE, Offer.NOTHING, 9, ""),
        ("state IN (", SuggestContext.VALUE, Offer.VALUES, 10, ""),
        ("state IN (Todo", SuggestContext.VALUE, Offer.VALUES, 10, "Todo"),
        ("state IN (Todo, ", SuggestContext.VALUE, Offer.VALUES, 16, ""),
        ("state IN (Todo, Do", SuggestContext.VALUE, Offer.VALUES, 16, "Do"),
        ("state IN (Todo ", SuggestContext.KEYWORD, Offer.NOTHING, 15, ""),
        # after a complete comparison / ')' -> keyword
        ("state = Done ", SuggestContext.KEYWORD, Offer.KEYWORDS, 13, ""),
        ("state = Done OR", SuggestContext.KEYWORD, Offer.KEYWORDS, 13, "OR"),
        ("state IN (Todo)", SuggestContext.KEYWORD, Offer.KEYWORDS, 15, ""),
        ("(state = Done) ", SuggestContext.KEYWORD, Offer.KEYWORDS, 15, ""),
        ("assignee IS EMPTY ", SuggestContext.KEYWORD, Offer.KEYWORDS, 18, ""),
        # ORDER BY clause
        ("state = Done ORDER ", SuggestContext.KEYWORD, Offer.KEYWORDS, 19, ""),
        ("state = Done ORD", SuggestContext.KEYWORD, Offer.KEYWORDS, 13, "ORD"),
        ("ORDER BY ", SuggestContext.FIELD, Offer.SORTABLE_FIELDS, 9, ""),
        ("ORDER BY cre", SuggestContext.FIELD, Offer.SORTABLE_FIELDS, 9, "cre"),
        ("state = Done ORDER BY ", SuggestContext.FIELD, Offer.SORTABLE_FIELDS, 22, ""),
        ("ORDER BY created ", SuggestContext.KEYWORD, Offer.KEYWORDS, 17, ""),
        ("ORDER BY created de", SuggestContext.KEYWORD, Offer.KEYWORDS, 17, "de"),
        ("ORDER BY created DESC, ", SuggestContext.FIELD, Offer.SORTABLE_FIELDS, 23, ""),
        ("ORDER BY created DESC ", SuggestContext.KEYWORD, Offer.NOTHING, 22, ""),
        # malformed input degrades gracefully
        ("state = Done Done ", SuggestContext.KEYWORD, Offer.NOTHING, 18, ""),
        ("AND ", SuggestContext.KEYWORD, Offer.NOTHING, 4, ""),
        ("; nonsense", SuggestContext.FIELD, Offer.FIELDS, 0, "; nonsense"),
    ],
)
def test_context_positions(q, context, offer, replace_from, partial):
    detection = detect(q, len(q))
    assert detection.context is context
    assert detection.offer is offer
    assert detection.replace_from == replace_from
    assert detection.partial == partial


def test_detection_carries_the_field_in_play():
    assert detect("assignee = ", 11).field == "assignee"
    assert detect("show IN (RU", 11).field == "show"
    assert detect("state = Done ", 13).field is None  # keyword context: no field


def test_cursor_mid_query_completes_the_token_under_it():
    q = "state = Done AND priority = high"
    detection = detect(q, 5)  # inside 'state'
    assert detection.context is SuggestContext.FIELD
    assert (detection.replace_from, detection.partial) == (0, "state")
    detection = detect(q, 8)  # right after '= '
    assert detection.context is SuggestContext.VALUE
    assert (detection.field, detection.partial) == ("state", "")


@pytest.mark.parametrize(
    ("q", "replace_from", "partial", "quote"),
    [
        ('state = "In P', 8, "In P", '"'),
        ("state = 'don", 8, "don", "'"),
        ("state IN (Todo, 'In ", 16, "In ", "'"),
        ('title = "a\\"b', 8, 'a"b', '"'),
    ],
)
def test_inside_quotes_is_a_value_position(q, replace_from, partial, quote):
    detection = detect(q, len(q))
    assert detection.context is SuggestContext.VALUE
    assert detection.offer is Offer.VALUES
    assert (detection.replace_from, detection.partial, detection.quote) == (
        replace_from,
        partial,
        quote,
    )


def test_quote_where_no_value_belongs_offers_nothing():
    detection = detect('"orphan', 7)
    assert detection.context is SuggestContext.VALUE
    assert detection.offer is Offer.NOTHING
    assert (detection.replace_from, detection.partial, detection.quote) == (0, "orphan", '"')


# --- field context: builtins + registry + NOT ---


async def test_field_context_lists_builtins_registry_and_not():
    response = await respond("")
    assert response.context is SuggestContext.FIELD and response.field is None
    listed = values(response)
    for expected in ("state", "assignee", "label", "created", "notes", "show", "budget"):
        assert expected in listed
    assert KeywordSuggestion.NOT.value in listed
    inserts = by_value(response)
    assert inserts["state"] == "state"  # field names never quoted


async def test_not_is_not_offered_twice():
    assert KeywordSuggestion.NOT.value not in values(await respond("NOT "))


async def test_shadowed_cf_keys_are_not_suggested():
    defs = dict(DEFS) | {"state": cf("state", FieldType.TEXT), "in": cf("in", FieldType.TEXT)}
    listed = values(await respond("", defs=defs))
    assert listed.count("state") == 1  # the builtin, not the unreachable cf
    assert "in" not in listed


async def test_cf_field_detail_carries_name_and_type():
    response = await respond("sho")
    (suggestion,) = [s for s in response.suggestions if s.value == "show"]
    assert suggestion.detail == "Show (select)"


# --- operator context: op-tables per field type ---


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("project ", {"=", "!=", "IN", "NOT IN"}),
        ("state ", {"=", "!=", "IN", "NOT IN"}),
        ("category ", {"=", "!=", "IN", "NOT IN"}),
        ("kind ", {"=", "!=", "IN", "NOT IN"}),
        ("priority ", {"=", "!=", "IN", "NOT IN"}),
        ("assignee ", {"=", "!=", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"}),
        ("team ", {"=", "!=", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"}),
        ("label ", {"=", "!=", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"}),
        ("title ", {"=", "~"}),
        ("key ", {"=", "!=", "IN", "NOT IN"}),
        ("parent ", {"=", "!=", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"}),
        ("number ", {"=", "!=", ">", "<", ">=", "<="}),
        ("created ", {"=", "!=", ">", "<", ">=", "<="}),
        ("updated ", {"=", "!=", ">", "<", ">=", "<="}),
        ("notes ", {"=", "!=", "~", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"}),
        ("homepage ", {"=", "!=", "~", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"}),
        ("reviewer ", {"=", "!=", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"}),
        ("show ", {"=", "!=", "~", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"}),
        ("software ", {"=", "!=", "IN", "NOT IN", "IS EMPTY", "IS NOT EMPTY"}),
        ("budget ", {"=", "!=", ">", "<", ">=", "<=", "IS EMPTY", "IS NOT EMPTY"}),
        ("spent ", {"=", "!=", ">", "<", ">=", "<=", "IS EMPTY", "IS NOT EMPTY"}),
        ("due ", {"=", "!=", ">", "<", ">=", "<=", "IS EMPTY", "IS NOT EMPTY"}),
        ("billable ", {"=", "!=", "IS EMPTY", "IS NOT EMPTY"}),
        # planning fields (spec 14)
        ("cycle ", {"=", "!=", "IS EMPTY", "IS NOT EMPTY"}),
        ("release ", {"=", "!=", "IS EMPTY", "IS NOT EMPTY"}),
        ("blocks ", {"=", "IS EMPTY", "IS NOT EMPTY"}),
        ("blocked ", {"=", "IS EMPTY", "IS NOT EMPTY"}),
        ("start ", {"=", "!=", ">", "<", ">=", "<=", "IS EMPTY", "IS NOT EMPTY"}),
        ("target ", {"=", "!=", ">", "<", ">=", "<=", "IS EMPTY", "IS NOT EMPTY"}),
        ("ghost ", set()),  # unknown field: context reported, nothing offered
    ],
)
async def test_operator_tables_per_field_type(q, expected):
    response = await respond(q)
    assert response.context is SuggestContext.OPERATOR
    assert response.field == q.strip()
    assert set(values(response)) == expected


async def test_multi_word_operators_insert_verbatim():
    inserts = by_value(await respond("assignee "))
    assert inserts["IS EMPTY"] == "IS EMPTY"
    assert inserts["NOT IN"] == "NOT IN"


async def test_operator_partial_ranks_prefix_before_contains():
    # prefix matches (IN, IS EMPTY, IS NOT EMPTY) lead; NOT IN only contains 'i'
    assert values(await respond("assignee I")) == ["IN", "IS EMPTY", "IS NOT EMPTY", "NOT IN"]


async def test_unlexable_operator_tail_completes():
    response = await respond("state !")
    assert response.context is SuggestContext.OPERATOR
    assert values(response) == ["!="]
    assert response.replace_from == 6


# --- keyword context ---


async def test_keywords_after_a_complete_comparison():
    assert values(await respond("state = Done ")) == ["AND", "OR", "ORDER BY"]


async def test_order_by_not_offered_inside_parens():
    assert values(await respond("(state = Done ")) == ["AND", "OR"]
    assert values(await respond("(state = Done) ")) == ["AND", "OR", "ORDER BY"]


async def test_keyword_partial_filters():
    assert values(await respond("state = Done O")) == ["OR", "ORDER BY"]
    assert values(await respond("ORDER BY created de")) == ["DESC"]
    assert values(await respond("state = Done ORDER ")) == ["BY"]


async def test_is_empty_keywords_after_is():
    assert values(await respond("assignee IS ")) == ["EMPTY", "NOT EMPTY"]
    assert values(await respond("assignee IS NOT ")) == ["EMPTY"]
    assert values(await respond("team NOT ")) == ["IN"]


# --- ORDER BY field context: sortable only ---


async def test_order_by_offers_sortable_fields_only():
    listed = set(values(await respond("ORDER BY ")))
    assert listed == {
        "kind", "priority", "title", "number", "created", "updated", "flagged", "rank", "points",  # builtins
        "start", "target",  # RADD-1209: planning date order
        "state", "category",  # RADD-1176: workflow position / tier order
        "notes", "homepage", "reviewer", "show", "budget", "spent", "due", "billable",
    }
    assert "assignee" not in listed and "label" not in listed and "software" not in listed


# --- value context: enum + cf sources (no DB) ---


async def test_enum_value_sources():
    assert set(values(await respond("category = "))) == {c.value for c in StateCategory}
    assert set(values(await respond("kind IN ("))) == {k.value for k in ItemKind}
    assert set(values(await respond("priority = "))) == {p.value for p in Priority}


async def test_select_options_come_from_the_registry():
    response = await respond("show = ")
    assert response.field == "show"
    assert set(values(response)) == {"RUX", "BNX", "Main Show", "none"}
    assert set(values(await respond("software = "))) == {"Maya", "Houdini"}


async def test_boolean_cf_offers_bare_true_false():
    assert by_value(await respond("billable = ")) == {"false": "false", "true": "true"}


async def test_date_fields_offer_today_and_a_non_insertable_hint():
    # Spec 69: `today` (relative-date literal) leads, then the format hint.
    for q in ("created > ", "due = ", "updated <= ", "start > ", "target = "):
        response = await respond(q)
        today, hint = response.suggestions
        assert (today.value, today.insert) == ("today", "today")  # bare, never quoted
        assert (hint.value, hint.insert, hint.label) == (DATE_TEMPLATE, "", DATE_TEMPLATE)
        assert hint.detail == "date format hint"
    # the hint survives a typed partial (it is guidance, not a completion)
    assert values(await respond("created > 20")) == [DATE_TEMPLATE]
    # a typed prefix narrows to the literal (plus the exempt hint)
    assert values(await respond("created > tod")) == ["today", DATE_TEMPLATE]


@pytest.mark.parametrize("q", ["notes = ", "homepage ~ ", "budget > ", "spent >= ", "reviewer = ", "title = "])
async def test_free_form_fields_report_context_without_suggestions(q):
    response = await respond(q)
    assert response.context is SuggestContext.VALUE
    assert response.field == q.split()[0]
    assert response.suggestions == []


# --- ranking, quoting, limit ---


async def test_prefix_ranks_before_contains_then_alphabetical():
    assert values(await respond("te")) == [
        "team",  # prefix match leads; contains-matches follow alphabetically
        "category", "created", "epic.category", "epic.state", "notes",
        "parent.category", "parent.state", "reporter", "state", "updated",
    ]


async def test_mid_token_value_filter():
    assert values(await respond("show = R")) == ["RUX"]


async def test_spacey_and_reserved_values_get_quoted_inserts():
    inserts = by_value(await respond("show = "))
    assert inserts["RUX"] == "RUX"
    assert inserts["Main Show"] == '"Main Show"'
    assert inserts["none"] == '"none"'  # a literal spelled like the sentinel must quote


async def test_open_quote_is_respected_and_closed():
    inserts = by_value(await respond('show = "Ma'))
    assert inserts == {"Main Show": '"Main Show"'}
    inserts = by_value(await respond("show = 'Ma"))
    assert inserts == {"Main Show": "'Main Show'"}


async def test_quotes_inside_values_are_escaped():
    defs = dict(DEFS) | {"tricky": cf("tricky", FieldType.SELECT, ['say "hi"', "it's ok"])}
    inserts = by_value(await respond("tricky = ", defs=defs))
    assert inserts['say "hi"'] == '"say \\"hi\\""'
    assert inserts["it's ok"] == '"it\'s ok"'


async def test_suggestions_are_capped():
    options = [f"option {i:02d}" for i in range(MAX_SUGGESTIONS + 10)]
    defs = dict(DEFS) | {"big": cf("big", FieldType.SELECT, options)}
    response = await respond("big = ", defs=defs)
    assert len(response.suggestions) == MAX_SUGGESTIONS


async def test_cursor_defaults_to_end_and_clamps():
    response = await respond("state = Do", cursor=None)
    assert (response.context, response.replace_from) == (SuggestContext.VALUE, 8)
    response = await respond("state = Do", cursor=999)
    assert response.replace_from == 8
    response = await respond("state = Do", cursor=0)
    assert (response.context, response.replace_from) == (SuggestContext.FIELD, 0)


# --- value sources against live data (rolled back afterwards) ---


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@dataclass
class Live:
    project_a: Project
    project_b: Project
    actor: User  # instance admin
    member: User  # plain active user (global member floor)
    outsider: User  # active, never granted anything (spec 86: still a member floor)
    inactive: User  # deactivated — denied everything


@pytest.fixture
async def live(db) -> Live:
    run = uuid.uuid4().hex[:8]
    project_a = await projects_service.create_project(
        db, ProjectCreate(key="SGA", name="Suggest A")
    )
    project_b = await projects_service.create_project(
        db, ProjectCreate(key="SGB", name="Suggest B")
    )
    await workflow.create_state(
        db,
        StateCreate(project_id=project_b.id, name="Blocked QA", category=StateCategory.IN_PROGRESS),
    )
    await teams_service.create_team(db, TeamCreate(name="FX Crew"))
    await labels_service.resolve_labels(db, ["urgent", "needs info"])
    actor = User(
        email=f"admin-{run}@example.com", name="Suggest Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    member = User(email=f"alice-{run}@example.com", name="Alice Painter")
    inactive = User(email=f"bob-{run}@example.com", name="Bob Gone", active=False)
    outsider = User(email=f"eve-{run}@example.com", name="Eve Outside")
    db.add_all([actor, member, inactive, outsider])
    await db.flush()
    default_a = next(s for s in await workflow.list_states(db, project_a.id) if s.is_default)
    default_b = next(s for s in await workflow.list_states(db, project_b.id) if s.is_default)
    db.add_all(
        [
            WorkItem(project_id=project_a.id, number=1, kind=ItemKind.ISSUE.value,
                     title="Fire sim explodes", state_id=default_a.id,
                     priority=Priority.NORMAL.value, custom_fields={}),
            WorkItem(project_id=project_a.id, number=2, kind=ItemKind.ISSUE.value,
                     title="Roto cleanup", state_id=default_a.id,
                     priority=Priority.NORMAL.value, custom_fields={}),
            WorkItem(project_id=project_a.id, number=12, kind=ItemKind.ISSUE.value,
                     title="Layout pass", state_id=default_a.id,
                     priority=Priority.NORMAL.value, custom_fields={}),
            WorkItem(project_id=project_b.id, number=1, kind=ItemKind.ISSUE.value,
                     title="Other project item", state_id=default_b.id,
                     priority=Priority.NORMAL.value, custom_fields={}),
        ]
    )
    await db.flush()
    return Live(project_a, project_b, actor, member, outsider, inactive)


def project_scope(live: Live) -> SuggestScope:
    return SuggestScope(project=live.project_a)


def global_scope(live: Live) -> SuggestScope:
    return SuggestScope()


async def test_state_values_narrow_to_the_project(db, live):
    listed = values(await respond("state = ", session=db, scope=project_scope(live)))
    assert "In Progress" in listed
    assert "Blocked QA" not in listed  # project B's extra state is out of scope


async def test_state_values_global_and_deduped(db, live):
    response = await respond("state = ", session=db, scope=global_scope(live))
    listed = values(response)
    assert "Blocked QA" in listed
    assert len(listed) == len(set(listed))  # names shared across projects appear once
    inserts = by_value(response)
    assert inserts["In Progress"] == '"In Progress"'  # spacey name -> quoted insert
    assert inserts["Done"] == "Done"


async def test_assignee_offers_me_none_then_active_users(db, live):
    listed = values(await respond("assignee = ", session=db, scope=global_scope(live)))
    assert listed[:2] == ["me", "none"]  # sentinels lead
    assert all("bob-" not in value for value in listed)  # inactive users excluded
    # Enumeration is global (every active user) + capped, so match this test's
    # member by its unique local-part rather than asserting the whole list.
    local = live.member.email.split("@")[0]
    response = await respond(f"assignee = {local}", session=db, scope=global_scope(live))
    (member_row,) = [s for s in response.suggestions if s.value == live.member.email]
    assert (member_row.label, member_row.detail) == ("Alice Painter", live.member.email)
    assert member_row.insert == live.member.email  # emails lex as barewords: no quotes


async def test_assignee_matches_display_names_too(db, live):
    listed = values(await respond("assignee = pain", session=db, scope=global_scope(live)))
    assert listed == [live.member.email]  # matched via the 'Alice Painter' label


async def test_sentinels_lose_meaning_inside_quotes(db, live):
    local = live.member.email.split("@")[0]
    response = await respond(f'assignee = "{local}', session=db, scope=global_scope(live))
    listed = values(response)
    assert "me" not in listed and "none" not in listed
    assert by_value(response)[live.member.email] == f'"{live.member.email}"'


async def test_team_offers_none_then_names(db, live):
    # "none" sentinel leads the unfiltered team list.
    assert values(await respond("team = ", session=db, scope=global_scope(live)))[0] == "none"
    # Teams enumerate globally, so surface this test's team under a prefix.
    response = await respond("team = FX", session=db, scope=global_scope(live))
    assert "FX Crew" in values(response)
    assert by_value(response)["FX Crew"] == '"FX Crew"'  # spacey name -> quoted


async def test_label_names_with_quoting(db, live):
    # Labels enumerate globally + capped; a uniquely-named spacey label surfaces
    # deterministically under its own prefix.
    token = uuid.uuid4().hex[:8]
    spacey = f"lbl{token} needs info"
    await labels_service.resolve_labels(db, [spacey])
    response = await respond(f"label = lbl{token}", session=db, scope=global_scope(live))
    assert spacey in values(response)
    assert by_value(response)[spacey] == f'"{spacey}"'  # spacey name -> quoted


async def test_project_offers_keys(db, live):
    # Projects enumerate globally; SGA/SGB are unique to this test's fixture.
    listed = values(await respond("project = SG", session=db, scope=global_scope(live)))
    assert "SGA" in listed and "SGB" in listed


async def test_item_keys_match_the_typed_prefix(db, live):
    assert values(await respond("key = SGA-1", session=db, scope=global_scope(live))) == [
        "SGA-1",
        "SGA-12",
    ]
    listed = values(await respond("key = SG", session=db, scope=global_scope(live)))
    assert {"SGA-1", "SGA-2", "SGA-12", "SGB-1"} <= set(listed)


async def test_item_keys_narrow_to_the_project(db, live):
    listed = values(await respond("key = SG", session=db, scope=project_scope(live)))
    assert listed == ["SGA-1", "SGA-12", "SGA-2"]  # alphabetical within prefix matches


async def test_parent_offers_none_then_keys(db, live):
    listed = values(await respond("parent = ", session=db, scope=project_scope(live)))
    assert listed[0] == "none"
    assert "SGA-1" in listed and "SGB-1" not in listed


async def test_item_key_suggestions_carry_the_title(db, live):
    response = await respond("key = SGA-1", session=db, scope=global_scope(live))
    assert response.suggestions[0].detail == "Fire sim explodes"


async def test_cycle_release_and_block_value_sources(db, live):
    from datetime import date

    from radd.modules.cycles import service as cycles_service
    from radd.modules.cycles.schemas import CycleCreate
    from radd.modules.releases import service as releases_service
    from radd.modules.releases.schemas import ReleaseCreate

    await cycles_service.create_cycle(
        db,
        CycleCreate(
            name="Sprint 7",
            start_date=date(2026, 7, 1), end_date=date(2026, 7, 14),
        ),
        today=date(2026, 7, 17),
    )
    await releases_service.create_release(
        db, ReleaseCreate(project_id=live.project_a.id, name="Beans", version="BNX.2.3")
    )
    # cycle: global names + none sentinel; spacey name -> quoted insert
    cycle = await respond("cycle = ", session=db, scope=global_scope(live))
    assert cycle.context is SuggestContext.VALUE and cycle.field == "cycle"
    assert values(cycle)[0] == "none"
    assert by_value(cycle)["Sprint 7"] == '"Sprint 7"'
    # release: project versions
    release = await respond("release = ", session=db, scope=project_scope(live))
    assert values(release) == ["none", "BNX.2.3"]
    # blocks / blocked resolve item keys (like key/parent)
    blocks = await respond("blocks = SGA-1", session=db, scope=project_scope(live))
    assert blocks.field == "blocks"
    assert "SGA-1" in values(blocks) and "SGB-1" not in values(blocks)
    blocked = await respond("blocked = ", session=db, scope=project_scope(live))
    assert {"SGA-1", "SGA-2", "SGA-12"} <= set(values(blocked))


# --- the endpoint entry: scope authorization ---


async def test_suggest_denies_inactive_users_only(db, live):
    # Spec 86: an ACTIVE user without a membership row is a member (floor);
    # only a deactivated account is denied.
    with pytest.raises(ForbiddenError):
        await suggest(
            db, actor=live.inactive,
            project_id=None, q="", cursor=None,
        )
    response = await suggest(
        db, actor=live.outsider,
        project_id=None, q="", cursor=None,
    )
    assert response.suggestions


async def test_suggest_allows_any_active_member(db, live):
    response = await suggest(
        db, actor=live.member,
        project_id=live.project_a.id, q="state = ", cursor=None,
    )
    assert response.context is SuggestContext.VALUE
    assert by_value(response)["In Progress"] == '"In Progress"'


async def test_suggest_rejects_an_unknown_project(db, live):
    with pytest.raises(NotFoundError):
        await suggest(
            db, actor=live.actor,
            project_id=uuid.uuid4(), q="", cursor=None,
        )


async def test_suggest_uses_the_registry_in_scope(db, live):
    from radd.modules.fields import service as fields_service
    from radd.modules.fields.schemas import FieldDefinitionCreate

    await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            key="shot", name="Shot",
            type=FieldType.SELECT, options=["010", "020"],
        ),
    )
    response = await suggest(
        db, actor=live.actor,
        project_id=None, q="shot = ", cursor=None,
    )
    assert set(values(response)) == {"010", "020"}
