"""SLQ core tests (spec 10): lexer/parser round-trips + precedence, every operator
per field type, error positions + did-you-mean, and compile smoke against a live
session (Postgres from compose, same as the demo flows).

Pure lex/parse/compile tests pass `session=None` — the compiler only touches the
session to resolve label names, so label-free queries never await the DB.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.fields.models import FieldDefinition
from radd.modules.fields.types import FieldType
from radd.modules.items.models import WorkItem
from radd.modules.items.slq import SlqError, compile_query, parse, render
from radd.modules.items.slq.lexer import TokenKind, tokenize
from radd.modules.items.slq.parser import (
    BoolExpr,
    BoolOp,
    Comparison,
    EmptyCheck,
    Membership,
    NotExpr,
    OrderTerm,
    Query,
    Value,
)

USER_ID = uuid.uuid4()


def cf(key: str, field_type: FieldType, options: list[str] | None = None) -> FieldDefinition:
    return FieldDefinition(
        id=uuid.uuid4(),
        key=key,
        name=key,
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
        cf("show", FieldType.SELECT, ["RUX", "BNX"]),
        cf("software", FieldType.MULTI_SELECT, ["Maya", "Houdini"]),
        cf("budget", FieldType.NUMBER),
        cf("spent", FieldType.DURATION),
        cf("due", FieldType.DATE),
        cf("billable", FieldType.BOOLEAN),
    )
}


async def compile_text(text: str, project_id: uuid.UUID | None = None, session=None):
    return await compile_query(
        session,
        parse(text),
        definitions_by_key=DEFS,
        current_user_id=USER_ID,
        project_id=project_id,
    )


def error_of(callable_or_coro):
    with pytest.raises(SlqError) as info:
        callable_or_coro()
    return info.value


# --- lexer ---


def test_lexer_tokens_and_positions():
    tokens = tokenize("state = 'In Progress'")
    assert [(t.kind, t.text, t.position) for t in tokens] == [
        (TokenKind.WORD, "state", 0),
        (TokenKind.OP, "=", 6),
        (TokenKind.STRING, "In Progress", 8),
        (TokenKind.EOF, "end of query", 21),
    ]


def test_lexer_two_character_operators_win():
    tokens = tokenize("number >= 5 AND number <= 7 AND number != 6")
    ops = [t.text for t in tokens if t.kind is TokenKind.OP]
    assert ops == [">=", "<=", "!="]


def test_lexer_barewords_cover_emails_keys_dates():
    words = [t.text for t in tokenize("a@b.co TD-12 2026-07-17 snake_key 1.5")][:-1]
    assert words == ["a@b.co", "TD-12", "2026-07-17", "snake_key", "1.5"]


def test_lexer_string_escapes():
    tokens = tokenize(r"title = 'it\'s \\ fine'")
    assert tokens[2].text == r"it's \ fine"


def test_lexer_unterminated_string_position():
    error = error_of(lambda: tokenize("title = 'oops"))
    assert error.position == 8
    assert "unterminated" in str(error)


def test_lexer_unexpected_character_position():
    error = error_of(lambda: tokenize("state ; done"))
    assert error.position == 6


# --- parser ---


def test_and_binds_tighter_than_or():
    query = parse("a = 1 AND b = 2 OR c = 3")
    assert isinstance(query.where, BoolExpr) and query.where.op is BoolOp.OR
    left, right = query.where.operands
    assert isinstance(left, BoolExpr) and left.op is BoolOp.AND
    assert isinstance(right, Comparison) and right.field == "c"


def test_parens_override_precedence():
    query = parse("a = 1 AND (b = 2 OR c = 3)")
    assert isinstance(query.where, BoolExpr) and query.where.op is BoolOp.AND
    assert isinstance(query.where.operands[1], BoolExpr)
    assert query.where.operands[1].op is BoolOp.OR


def test_not_on_comparison_and_group():
    query = parse("NOT state = Done AND NOT (a = 1 OR b = 2)")
    first, second = query.where.operands
    assert isinstance(first, NotExpr) and isinstance(first.operand, Comparison)
    assert isinstance(second, NotExpr) and isinstance(second.operand, BoolExpr)


def test_membership_and_empty_forms():
    query = parse("priority IN (high, blocker) AND team NOT IN (Core) AND assignee IS NOT EMPTY")
    membership, negated, empty = query.where.operands
    assert membership == Membership("priority", (Value("high"), Value("blocker")))
    assert negated == Membership("team", (Value("Core"),), negated=True)
    assert empty == EmptyCheck("assignee", negated=True)


def test_keywords_are_case_insensitive():
    query = parse("state = Done and label = fx oR title ~ x OrDeR bY created dEsC")
    assert isinstance(query.where, BoolExpr) and query.where.op is BoolOp.OR
    assert query.order == (OrderTerm("created", descending=True),)


def test_empty_query_and_bare_order_by():
    assert parse("") == Query()
    assert parse("  ") == Query()
    assert parse("ORDER BY created DESC, number") == Query(
        order=(OrderTerm("created", descending=True), OrderTerm("number"))
    )


def test_quoted_values_never_collide_with_keywords():
    query = parse("label = 'and' AND title = 'none'")
    first, second = query.where.operands
    assert first.value == Value("and", quoted=True)
    assert second.value == Value("none", quoted=True)


def test_reserved_word_as_bare_value_is_rejected():
    error = error_of(lambda: parse("label = and"))
    assert error.position == 8
    assert "reserved word" in str(error)


@pytest.mark.parametrize(
    ("text", "position", "fragment"),
    [
        ("state", 5, "expected an operator after 'state'"),
        ("state =", 7, "expected a value"),
        ("state IN", 8, "expected '(' after IN"),
        ("state IN (a", 11, "expected ')' or ','"),
        ("state IN ()", 10, "expected a value"),
        ("(a = 1", 6, "expected ')'"),
        ("a = 1 b = 2", 6, "expected AND, OR or ORDER BY"),
        ("assignee IS", 11, "expected EMPTY after IS"),
        ("team NOT EMPTY", 9, "expected IN after NOT"),
        ("ORDER BY", 8, "expected a field name in ORDER BY"),
        ("AND a = 1", 0, "expected a field name"),
    ],
)
def test_parse_error_positions(text: str, position: int, fragment: str):
    error = error_of(lambda: parse(text))
    assert error.position == position
    assert fragment in str(error)


@pytest.mark.parametrize(
    "text",
    [
        "label = urgent AND (show = RUX OR show = BNX) AND NOT state = Done",
        "assignee IN (me, none, a@b.co) AND team IS EMPTY",
        "priority NOT IN (low, normal) OR title ~ 'fire \\'sim\\''",
        "NOT (a = 1 AND b = 2) OR (c = 3 OR d = 4)",
        "created >= 2026-01-01 ORDER BY priority DESC, number",
        "ORDER BY created",
        "",
    ],
)
def test_render_round_trips(text: str):
    query = parse(text)
    assert parse(render(query)) == query
    assert parse(render(parse(render(query)))) == query  # canonical fixpoint


# --- compiler: every operator per builtin field ---


@pytest.mark.parametrize(
    "text",
    [
        "project = FX",
        "project != FX",
        "project IN (FX, TD)",
        "project NOT IN (FX)",
        "state = 'In Progress'",
        "state != Done",
        "state IN (Todo, Done)",
        "category = triage",
        "category != done",
        "category IN (triage, in_progress)",
        "kind = epic",
        "kind != subtask",
        "kind IN (issue, epic)",
        "priority = blocker",
        "priority != low",
        "priority IN (high, blocker)",
        "assignee = me",
        "assignee = none",
        "assignee = a@b.co",
        "assignee != me",
        "assignee != none",
        "assignee IN (me, none, a@b.co)",
        "assignee NOT IN (a@b.co)",
        "assignee IS EMPTY",
        "assignee IS NOT EMPTY",
        "team = Core",
        "team != Core",
        "team = none",
        "team IN (Core, none)",
        "team IS EMPTY",
        "title = 'exact title'",
        "title ~ sim",
        "key = TD-12",
        "key != TD-12",
        "key IN (TD-1, DEV-2)",
        # `parent = <key>` forms moved to test_slq_ancestors.py: bare epic/parent
        # keys resolve against the DB at compile time since spec 83.
        "parent = none",
        "parent IS EMPTY",
        "number = 5",
        "number != 5",
        "number > 5",
        "number < 5",
        "number >= 5",
        "number <= 5",
        "created = 2026-07-17",
        "created != 2026-07-17",
        "created > 2026-07-17",
        "created < 2026-07-17",
        "created >= 2026-07-17",
        "updated <= 2026-07-17",
        # planning fields (spec 14)
        "cycle = Sprint1",
        "cycle != Sprint1",
        "cycle = none",
        "cycle IS EMPTY",
        "cycle IS NOT EMPTY",
        "release = BNX.2.3",
        "release != BNX.2.3",
        "release = none",
        "release IS EMPTY",
        "blocks IS EMPTY",
        "blocks IS NOT EMPTY",
        "blocks = TD-5",
        "blocked IS EMPTY",
        "blocked IS NOT EMPTY",
        "blocked = TD-5",
        "start = 2026-07-17",
        "start > 2026-01-01",
        "start IS EMPTY",
        "start IS NOT EMPTY",
        "target <= 2026-12-31",
        "target >= 2026-01-01",
        "target != 2026-07-17",
        "target IS EMPTY",
    ],
)
async def test_builtin_field_operators_compile(text: str):
    compiled = await compile_text(text)
    assert compiled.where is not None


# --- compiler: every operator per custom-field type ---


@pytest.mark.parametrize(
    "text",
    [
        "notes = x",
        "notes != x",
        "notes ~ x",
        "notes IN (x, y)",
        "notes IS EMPTY",
        "homepage ~ example.com",
        "homepage = 'https://example.com'",
        "reviewer = someone",
        "reviewer != someone",
        "reviewer IN (a, b)",
        "reviewer IS NOT EMPTY",
        "show = RUX",
        "show != RUX",
        "show ~ RU",
        "show IN (RUX, BNX)",
        "show NOT IN (RUX)",
        "show IS EMPTY",
        "software = Maya",
        "software != Maya",
        "software IN (Maya, Houdini)",
        "software IS EMPTY",
        "software IS NOT EMPTY",
        "budget = 5",
        "budget != 5.5",
        "budget > 5",
        "budget < 5",
        "budget >= 5",
        "budget <= 5",
        "budget IS EMPTY",
        "spent > 90",
        "spent <= 30",
        "due = 2026-07-17",
        "due != 2026-01-01",
        "due > 2026-01-01",
        "due <= 2026-12-31",
        "due IS EMPTY",
        "billable = true",
        "billable != false",
        "billable IS EMPTY",
    ],
)
async def test_custom_field_operators_compile(text: str):
    compiled = await compile_text(text)
    assert compiled.where is not None


@pytest.mark.parametrize(
    ("text", "position", "fragment"),
    [
        ("number ~ 5", 7, "operator '~' is not valid for field 'number'"),
        ("created ~ 2026-01-01", 8, "operator '~' is not valid"),
        ("title > x", 6, "operator '>' is not valid for field 'title'"),
        ("title IN (a, b)", 0, "IN is not valid for field 'title'"),
        ("number IN (1, 2)", 0, "IN is not valid for field 'number'"),
        ("state IS EMPTY", 0, "IS EMPTY is not valid for field 'state'"),
        ("project IS EMPTY", 0, "IS EMPTY is not valid for field 'project'"),
        ("budget ~ 5", 7, "operator '~' is not valid"),
        ("software > Maya", 9, "operator '>' is not valid"),
        ("software ~ Maya", 9, "operator '~' is not valid"),
        ("billable ~ true", 9, "operator '~' is not valid"),
        ("due IN (2026-01-01)", 0, "IN is not valid for field 'due'"),
        ("reviewer ~ x", 9, "operator '~' is not valid"),
        # planning fields (spec 14)
        ("cycle ~ Sprint1", 6, "operator '~' is not valid for field 'cycle'"),
        ("cycle > Sprint1", 6, "operator '>' is not valid for field 'cycle'"),
        ("cycle IN (a, b)", 0, "IN is not valid for field 'cycle'"),
        ("release IN (a)", 0, "IN is not valid for field 'release'"),
        ("blocks != TD-5", 7, "operator '!=' is not valid for field 'blocks'"),
        ("blocked > TD-5", 8, "operator '>' is not valid for field 'blocked'"),
        ("blocks IN (TD-1)", 0, "IN is not valid for field 'blocks'"),
        ("start ~ 2026-01-01", 6, "operator '~' is not valid for field 'start'"),
        ("target IN (2026-01-01)", 0, "IN is not valid for field 'target'"),
    ],
)
async def test_type_invalid_operators(text: str, position: int, fragment: str):
    with pytest.raises(SlqError) as info:
        await compile_text(text)
    assert info.value.position == position
    assert fragment in str(info.value)


@pytest.mark.parametrize(
    ("text", "position", "fragment"),
    [
        ("shwo = RUX", 0, "unknown field 'shwo' — did you mean 'show'?"),
        # 'stat' is one edit from both 'state' and the new 'start' field; alphabetically first wins.
        ("stat = Done", 0, "unknown field 'stat' — did you mean 'start'?"),
        ("ghost = 1", 0, "unknown field 'ghost'"),
        ("show = RUX ORDER BY sohw", 20, "did you mean 'show'?"),
        ("category = nope", 11, "invalid category 'nope'"),
        ("kind = task", 7, "invalid kind 'task'"),
        ("priority = urgent", 11, "invalid priority 'urgent'"),
        ("number = five", 9, "expects a whole number"),
        ("created > yesterday", 10, "expects a date (YYYY-MM-DD)"),
        ("created > 2026-13-40", 10, "expects a date (YYYY-MM-DD)"),
        ("budget > lots", 9, "expects a number"),
        ("billable = maybe", 11, "expects true or false"),
        ("due = tomorrow", 6, "expects a date"),
        ("key = TD12", 6, "expected an item key like TD-12"),
        ("parent = 42", 9, "expected an item key like TD-12"),
        ("title = none", 8, "'none' is not a valid value for field 'title'"),
        ("team = me", 7, "'me' is not a valid value for field 'team'"),
        ("show = none", 7, "'none' is not a valid value for field 'show'"),
        ("ORDER BY label", 9, "field 'label' is not sortable"),
        ("ORDER BY assignee", 9, "field 'assignee' is not sortable"),
        ("ORDER BY software", 9, "field 'software' is not sortable"),
        # planning fields (spec 14)
        ("cycle = me", 8, "'me' is not a valid value for field 'cycle'"),
        ("start > yesterday", 8, "expects a date (YYYY-MM-DD)"),
        ("target = soon", 9, "expects a date (YYYY-MM-DD)"),
        ("blocks = TD5", 9, "expected an item key like TD-12"),
        ("blocked = 42", 10, "expected an item key like TD-12"),
        ("ORDER BY cycle", 9, "field 'cycle' is not sortable"),
        ("ORDER BY start", 9, "field 'start' is not sortable"),
        ("ORDER BY blocks", 9, "field 'blocks' is not sortable"),
    ],
)
async def test_compile_errors_carry_positions(text: str, position: int, fragment: str):
    with pytest.raises(SlqError) as info:
        await compile_text(text)
    assert info.value.position == position
    assert fragment in str(info.value)


async def test_me_compiles_to_the_current_user():
    compiled = await compile_text("assignee = me")
    assert USER_ID.hex in str(
        compiled.where.compile(compile_kwargs={"literal_binds": True})
    )


async def test_none_and_empty_are_equivalent_for_assignee():
    by_none = await compile_text("assignee = none")
    by_empty = await compile_text("assignee IS EMPTY")
    assert str(by_none.where) == str(by_empty.where)


async def test_quoted_none_is_a_literal_not_the_sentinel():
    compiled = await compile_text("assignee = 'none'")
    assert "users.email" in str(compiled.where)  # looked up as an email, not IS NULL


async def test_date_comparisons_use_whole_day_windows():
    eq = str((await compile_text("created = 2026-07-17")).where)
    assert "created_at >=" in eq and "created_at <" in eq
    gt = str((await compile_text("created > 2026-07-17")).where)
    assert "created_at >=" in gt  # strictly after the day == from the next day's start


async def test_order_by_compiles_priority_rank_and_direction():
    compiled = await compile_text("ORDER BY priority DESC, number")
    assert len(compiled.order) == 2
    assert "CASE" in str(compiled.order[0])
    assert str(compiled.order[0]).endswith("DESC")
    assert compiled.joins == ()


async def test_order_by_state_and_category_join_the_workflow_rows():
    """RADD-1176: `state` sorts by workflow position (name as tiebreak),
    `category` by tier position first; both reach `states` through a JOIN the
    statement builders apply — never a per-row subquery (5× slower, measured)."""
    compiled = await compile_text("ORDER BY state DESC, updated")
    assert [str(c) for c in compiled.order] == [
        "states.position DESC", "states.name DESC", "work_items.updated_at ASC"
    ]
    assert [t.__tablename__ for t, _ in compiled.joins] == ["states"]
    assert "SELECT" not in " ".join(str(c) for c in compiled.order)

    compiled = await compile_text("ORDER BY category, state")
    assert [str(c) for c in compiled.order][:2] == [
        "state_categories.position ASC", "states.position ASC"
    ]
    assert [t.__tablename__ for t, _ in compiled.joins] == ["states", "state_categories"]


# --- compile smoke against a live session ---


async def test_past_cycle_field_compiles():
    """spec 56: the carryover-trail field — equality, membership, none, EMPTY."""
    for text in (
        'past_cycle = "PIPE - 115"',
        "past_cycle IN (A, B)",
        "past_cycle != Kickoff",
        "past_cycle = none",
        "past_cycle IS NOT EMPTY",
    ):
        compiled = await compile_text(text)
        assert compiled.where is not None


@pytest.fixture
async def db_session():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()  # flushed rows never persist
    await engine.dispose()


async def test_negated_relations_include_items_without_the_relation(db_session):
    """RADD-1139: `assignee != x` / `NOT IN` are the complement of the positive
    form, so the unassigned item is on the negative side rather than lost to
    both; `!= none` still means assigned. The same rule rides `type`."""
    from radd.modules.auth.models import User
    from radd.modules.auth.types import InstanceRole
    from radd.modules.items import service as items
    from radd.modules.items.filters import ItemListFilters
    from radd.modules.items.schemas import ItemCreate, ItemUpdate
    from radd.modules.itemtypes import service as itemtypes
    from radd.modules.projects import service as projects
    from radd.modules.projects.schemas import ProjectCreate

    actor = User(
        email=f"neg-{uuid.uuid4().hex[:8]}@example.com",
        name="Negation Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db_session.add(actor)
    await db_session.flush()
    project = await projects.create_project(
        db_session, ProjectCreate(key=f"NEG{uuid.uuid4().hex[:4].upper()}", name="Negation")
    )
    types = {t.name: t for t in await itemtypes.list_types(db_session, project.id)}
    bug, task = types["Bug"], types["Task"]
    for title, assignee, type_ in (
        ("mine bug", actor.id, bug.id),
        ("mine task", actor.id, task.id),
        ("unassigned untyped", None, None),
    ):
        created = await items.create_item(
            db_session,
            ItemCreate(project_id=project.id, title=title, assignee_id=assignee, type_id=type_),
            actor,
        )
        if type_ is None:  # creation falls back to the default type; an explicit null clears
            await items.update_item(db_session, created.id, ItemUpdate(type_id=None), actor)

    async def titles(q: str) -> set[str]:
        rows = await items.list_items(
            db_session,
            actor=actor,
            filters=ItemListFilters(project_id=project.id),
            q=q,
            limit=50,
            offset=0,
        )
        return {r.title for r in rows}

    everything = {"mine bug", "mine task", "unassigned untyped"}
    assert await titles(f"assignee = {actor.email}") == {"mine bug", "mine task"}
    assert await titles(f"assignee != {actor.email}") == {"unassigned untyped"}
    assert await titles(f"assignee NOT IN ({actor.email})") == {"unassigned untyped"}
    assert await titles("assignee != me") == {"unassigned untyped"}
    assert await titles("assignee != none") == {"mine bug", "mine task"}
    assert await titles("assignee NOT IN (none)") == {"mine bug", "mine task"}
    assert await titles("type = Bug") == {"mine bug"}
    assert await titles("type != Bug") == {"mine task", "unassigned untyped"}
    assert await titles("type NOT IN (Bug, Task)") == {"unassigned untyped"}
    for positive, negative in (("assignee = me", "assignee != me"), ("type = Bug", "type != Bug")):
        assert await titles(positive) | await titles(negative) == everything
        assert await titles(positive) & await titles(negative) == set()


async def test_order_by_state_lists_items_in_workflow_order(db_session):
    """RADD-1176, end to end: three items in three states, listed in the
    workflow's position order, and in reverse with DESC; category groups the
    tiers and `state, updated DESC` orders within a state."""
    from radd.modules.auth.models import User
    from radd.modules.auth.types import InstanceRole
    from radd.modules.items import service as items
    from radd.modules.items.filters import ItemListFilters
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects
    from radd.modules.projects.schemas import ProjectCreate
    from radd.modules.workflow import service as workflow

    actor = User(
        email=f"ord-{uuid.uuid4().hex[:8]}@example.com", name="Order Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db_session.add(actor)
    await db_session.flush()
    project = await projects.create_project(
        db_session, ProjectCreate(key=f"ORD{uuid.uuid4().hex[:4].upper()}", name="Ordering")
    )
    states = sorted(await workflow.list_states(db_session, project.id), key=lambda s: s.position)
    first, middle, last = states[0], states[len(states) // 2], states[-1]
    # Created in the OPPOSITE order to the workflow, so created-desc (the
    # default) and workflow order disagree and the sort is observable.
    for state in (last, middle, first):
        await items.create_item(
            db_session,
            ItemCreate(project_id=project.id, title=f"in {state.name}", state_id=state.id),
            actor,
        )

    async def titles(q: str) -> list[str]:
        rows = await items.list_items(
            db_session, actor=actor, filters=ItemListFilters(project_id=project.id),
            q=q, limit=50, offset=0,
        )
        return [r.title for r in rows]

    forward = [f"in {s.name}" for s in (first, middle, last)]
    assert await titles("ORDER BY state") == forward
    assert await titles("ORDER BY state DESC") == list(reversed(forward))
    assert await titles("ORDER BY state, updated DESC") == forward
    # `category`: tier position first, then the state's position within it.
    from sqlalchemy import select

    from radd.modules.workflow.models import StateCategoryDef

    tier_position = dict(
        (await db_session.execute(select(StateCategoryDef.key, StateCategoryDef.position))).all()
    )
    expected = [
        f"in {s.name}"
        for s in sorted((first, middle, last), key=lambda s: (tier_position[s.category_key], s.position))
    ]
    assert await titles("ORDER BY category") == expected


async def test_compile_smoke_executes_against_the_database(db_session):
    compiled = await compile_query(
        db_session,
        parse(
            "project = TD AND label IN (urgent, fx) AND state != Done AND assignee != me "
            "AND team IS EMPTY AND title ~ fix AND created >= 2020-01-01 "
            "AND (show = RUX OR software = Houdini OR budget > 1) AND parent IS EMPTY "
            "ORDER BY priority DESC, created"
        ),
        definitions_by_key=DEFS,
        current_user_id=USER_ID,
    )
    query = (
        select(WorkItem).where(compiled.where).order_by(*compiled.order).limit(5)
    )
    result = await db_session.execute(query)  # proves the SQL is valid Postgres
    assert result.scalars().all() is not None


async def test_issue_type_field_compiles(db_session):
    # Spec 51: the `type` builtin filters by issue-type name + IS [NOT] EMPTY.
    compiled = await compile_query(
        db_session,
        parse("type = Bug AND type IS NOT EMPTY AND type != Epic"),
        definitions_by_key={},
        current_user_id=USER_ID,
    )
    result = await db_session.execute(select(WorkItem).where(compiled.where).limit(1))
    assert result.scalars().all() is not None


async def test_planning_fields_compile_to_valid_postgres(db_session):
    """cycle/release subqueries, blocks/blocked EXISTS, and start/target dates (spec 14)."""
    compiled = await compile_query(
        db_session,
        parse(
            "cycle = Sprint1 AND release = BNX.2.3 AND blocks IS NOT EMPTY "
            "AND blocked IS EMPTY AND target IS NOT EMPTY AND start >= 2026-01-01 "
            "AND (cycle = none OR release IS EMPTY OR blocks = TD-1)"
        ),
        definitions_by_key=DEFS,
        current_user_id=USER_ID,
    )
    result = await db_session.execute(select(WorkItem).where(compiled.where).limit(5))
    assert result.scalars().all() is not None


async def test_every_stored_view_query_still_compiles(db_session):
    """The migration's converted output must parse + compile (live-data invariant)."""
    from radd.modules.items.listing import cf_definitions
    from radd.modules.views.models import View

    definitions = await cf_definitions(db_session, None)
    views = (await db_session.execute(select(View))).scalars().all()
    for view in views:
        if not view.query:
            continue
        compiled = await compile_query(
            db_session,
            parse(view.query),
            definitions_by_key=definitions,
            current_user_id=USER_ID,
            project_id=view.project_id,
        )
        await db_session.execute(select(WorkItem).where(compiled.where).limit(1))
