"""Node arity: once for the set, or once per item (RADD-918/919).

There is no LOOP in an automation graph. A back-edge would break the DAG the
validator rejects cycles against, and a nested-scope executor would grow every
budget and every report entry a dimension. What replaced it is a property of each
node — does it see the SET, or each ITEM — which needs no new graph shape,
because an action passes its input through either way and a router's ports mean
the same thing at both granularities.

These pin the parts that are easy to get subtly wrong:

* the defaults reproduce the pre-arity behaviour EXACTLY, which is what makes it
  a no-migration change;
* a gate emits only the branch it took (it used to emit an empty packet on the
  other one, which fired every universal action wired there);
* a per-item router PARTITIONS rather than routing;
* an action that runs once over a single item still gets that item, so
  `{{item.key}}` resolves on an ordinary event-triggered run.

Executor tests stub `_load` and `_one` — the fan-out SHAPE is what is new here,
and re-testing the planner through it would only make the failures harder to
read. The planner has its own tests in test_automations.py.
"""

import uuid

import pytest

from radd.kernel.registry import registries
from radd.kernel.specs import AutomationNodeSpec
from radd.modules.automations import executor, graph, nodes as nodes_registry, planning, templating
from radd.modules.automations.conditions import EventFacts
from radd.modules.automations.graph import Edge, Node, Packet
from radd.modules.automations.types import (
    ACTION_ARITY_CONFIGURABLE,
    ACTION_ARITY_DEFAULT,
    ARITY_PARAM,
    ITEM_ACTIONS,
    ActionType,
    AutomationNodeKind,
    NodeArity,
    NodePort,
)


# --- the defaults are the old behaviour, written down -------------------------


def test_the_arity_table_reproduces_the_historical_item_action_split():
    """`ITEM_ACTIONS` used to be a hand-written frozenset and is now derived from
    the arity table. If those ever disagree, every automation stored before this
    change starts running in a mode nobody chose — so the old list is spelled out
    here rather than derived from the same source it is checking."""
    historical = {
        ActionType.SET_STATE,
        ActionType.SET_PRIORITY,
        ActionType.SET_ASSIGNEE,
        # Fixed ITEM like SET_ASSIGNEE — a round-robin assign names the next
        # member, which only means anything for one item (RADD-1044).
        ActionType.ASSIGN_ROUND_ROBIN,
        ActionType.SET_TEAM,
        ActionType.ADD_LABEL,
        ActionType.REMOVE_LABEL,
        ActionType.SET_CYCLE,
        ActionType.SET_RELEASE,
        ActionType.SET_CUSTOM_FIELD,
        ActionType.ADD_COMMENT,
    }
    # RADD-1267 added the rest of what an item can have done to it — all item
    # mutations, so all per item. Listed apart from the historical set so the
    # invariant the test guards (the pre-RADD-918 split) stays legible.
    added = {
        ActionType.SET_PARENT,
        ActionType.SET_TYPE,
        ActionType.SET_REPORTER,
        ActionType.SET_DATES,
        ActionType.SET_ESTIMATE,
        ActionType.SET_FLAG,
        ActionType.SET_VISIBILITY,
        ActionType.LINK_ITEM,
        ActionType.ARCHIVE_ITEM,
        ActionType.ADD_WATCHER,
        ActionType.ADD_PARTICIPANT,
        ActionType.MOVE_TO_PROJECT,
    }
    assert set(ITEM_ACTIONS) == historical | added
    assert ACTION_ARITY_DEFAULT.keys() == set(ActionType), "every action needs a default"


def test_an_item_mutating_action_cannot_be_talked_into_running_once():
    """`set_state` at set arity would apply to whichever item happened to be
    first. The param is ignored for types that offer no choice, so hand-editing
    a stored graph cannot produce it."""
    node = Node(
        id="a",
        kind=AutomationNodeKind.ACTION,
        type="action.set_state",
        params={ARITY_PARAM: NodeArity.SET.value, "state": "Done"},
    )
    assert nodes_registry.arity_of(node) is NodeArity.ITEM


@pytest.mark.parametrize("action", sorted(ACTION_ARITY_CONFIGURABLE))
def test_a_configurable_action_honours_the_stored_arity(action):
    node = Node(
        id="a",
        kind=AutomationNodeKind.ACTION,
        type=f"action.{action.value}",
        params={ARITY_PARAM: NodeArity.ITEM.value},
    )
    assert nodes_registry.arity_of(node) is NodeArity.ITEM
    assert nodes_registry.arity_rule(node.type).configurable is True


def test_a_nonsense_arity_falls_back_to_the_default():
    node = Node(
        id="a",
        kind=AutomationNodeKind.ACTION,
        type="action.create_item",
        params={ARITY_PARAM: "sideways"},
    )
    assert nodes_registry.arity_of(node) is NodeArity.SET


# --- a contributed node's ports have to be wireable ---------------------------


def test_an_edge_may_name_a_port_no_NodePort_member_has():
    """The AI classifier's ports ARE its answers, which is the entire reason
    `ports_for(params)` exists — and `parse` coerced every edge port through
    `NodePort`, so an edge to `bug` was rejected before the validator ever asked
    the node. The feature was unreachable, not merely awkward."""
    nodes, edges = graph.parse(
        [
            {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {}},
            {"id": "c", "kind": "gate", "type": "ai.classify", "params": {"answers": ["bug", "feature"]}},
            {"id": "a", "kind": "action", "type": "action.add_label", "params": {"label": "x"}},
        ],
        [
            {"source": "t", "port": "out", "target": "c"},
            {"source": "c", "port": "bug", "target": "a"},
        ],
    )
    assert edges[1].port == "bug"

    def ports_of(node: Node) -> tuple[str, ...]:
        if node.type == "ai.classify":
            return (*node.params.get("answers", ()), "unavailable")
        return graph.default_ports(node)

    assert [n.id for n in graph.validate(nodes, edges, ports_of)] == ["t"]


# --- set-shaped tokens --------------------------------------------------------


FACTS = EventFacts(
    event_type="automation.scheduled", actor_id=None, actor_email=None, actor_name=None, payload={}
)
ITEMS = [
    {"key": "TD-1", "title": "First", "id": "1"},
    {"key": "TD-2", "title": "Second", "id": "2"},
]


def test_set_tokens_name_the_items_not_just_how_many():
    """`{{matched_count}}` was the whole vocabulary an action running once had:
    it could say "12 issues went stale" and never which twelve."""
    assert templating.render_template("{{items.count}}", FACTS, None, ITEMS) == "2"
    assert templating.render_template("{{items.keys}}", FACTS, None, ITEMS) == "TD-1, TD-2"
    assert templating.render_template("{{items.list}}", FACTS, None, ITEMS) == (
        "TD-1 — First\nTD-2 — Second"
    )


def test_an_empty_set_renders_empty_rather_than_verbatim():
    """A literal `{{items.keys}}` in a chat message reads as a broken automation;
    "0" and a blank list are the honest rendering of a run that matched nothing."""
    assert templating.render_template("{{items.count}}", FACTS, None, []) == "0"
    assert templating.render_template("{{items.keys}}", FACTS, None, []) == ""


# --- the executor's fan-out ---------------------------------------------------


class _Item:
    def __init__(self, item_id: uuid.UUID):
        self.id = item_id


@pytest.fixture
def spy(monkeypatch):
    """Record every `_one` call, and serve items without a database."""
    calls: list[dict] = []

    async def fake_load(_session, item_ids):
        return [(_Item(i), object()) for i in item_ids]

    async def fake_facts(_session, _rows):
        return {}

    async def fake_one(
        _session, node, stored, item, _project, _actor, _packet, scope, _name, _apply, _report,
        _facts=None,
    ):
        calls.append(
            {
                "node": node.id,
                "action": stored["type"],
                "item": item.id if item is not None else None,
                "scope": [i.id for i, _ in scope],
            }
        )
        # `_one` returns an `_Outcome` since spec 120 — the id of anything it
        # created AND the values it made addressable, because the id alone
        # cannot say `TD-42`.
        if stored["type"] != ActionType.CREATE_ITEM.value:
            return executor._Outcome()
        made = uuid.uuid4()
        return executor._Outcome(
            created_id=made, produced={"id": str(made), "key": "TD-9", "url": ""}
        )

    monkeypatch.setattr(executor, "_load", fake_load)
    monkeypatch.setattr(executor, "_one", fake_one)
    monkeypatch.setattr(planning, "load_item_facts", fake_facts)
    return calls


async def _walk(nodes, edges, item_ids=()):
    trigger = next(n for n in nodes if n.kind is AutomationNodeKind.TRIGGER)
    return await executor.walk(
        None,
        nodes=nodes,
        edges=edges,
        trigger=trigger,
        initial=Packet.of(FACTS, item=tuple(item_ids)),
        system_user=object(),
        automation_name="test",
        budget=executor.new_budget(),
        apply=True,
    )


TRIGGER = Node(id="t", kind=AutomationNodeKind.TRIGGER, type="trigger.event", params={})


def _action(node_id: str, action: str, **params) -> Node:
    return Node(
        id=node_id, kind=AutomationNodeKind.ACTION, type=f"action.{action}", params=params
    )


async def test_a_gate_does_not_emit_the_branch_it_did_not_take(spy):
    """THE bug this wave fixes. A gate used to emit an EMPTY packet on the
    untaken port, and universal actions ignore emptiness by design — so
    `gate → false → send_email("nobody touched it")` sent that mail on every run
    where somebody had, which is the exact opposite of what it says."""
    gate = Node(
        id="g",
        kind=AutomationNodeKind.GATE,
        type="gate.changed_by",
        params={"users": ["Ada"], "negate": False},
    )
    facts = EventFacts(
        event_type="item.updated", actor_id=None, actor_email=None, actor_name="Ada", payload={}
    )
    nodes = [TRIGGER, gate, _action("yes", "send_webhook", url="https://y"), _action("no", "send_webhook", url="https://n")]
    edges = [
        Edge("t", NodePort.OUT.value, "g"),
        Edge("g", NodePort.TRUE.value, "yes"),
        Edge("g", NodePort.FALSE.value, "no"),
    ]
    report = await executor.walk(
        None,
        nodes=nodes,
        edges=edges,
        trigger=TRIGGER,
        initial=Packet.of(facts, item=()),
        system_user=object(),
        automation_name="test",
        budget=executor.new_budget(),
        apply=True,
    )

    assert [call["node"] for call in spy] == ["yes"]
    # And the editor can tell "did not run" from "ran and found nothing".
    assert report.not_taken["g"] == [NodePort.FALSE.value]


async def test_a_filter_still_emits_both_ports_including_an_empty_one(spy):
    """Unchanged, and deliberately different from a gate: a filter PARTITIONS, so
    an empty subset is a real answer. "Nothing matched — tell me" is a working
    automation and stays one."""
    filter_node = Node(
        id="f", kind=AutomationNodeKind.FILTER, type="filter.slq", params={"slq": ""}
    )
    nodes = [TRIGGER, filter_node, _action("hit", "send_webhook", url="https://y"), _action("miss", "send_webhook", url="https://n")]
    edges = [
        Edge("t", NodePort.OUT.value, "f"),
        Edge("f", NodePort.MATCHED.value, "hit"),
        Edge("f", NodePort.UNMATCHED.value, "miss"),
    ]
    report = await _walk(nodes, edges, [uuid.uuid4()])

    assert sorted(call["node"] for call in spy) == ["hit", "miss"]
    assert report.per_node["f"] == {"in": 1, "matched": 1, "unmatched": 0}
    assert "f" not in report.not_taken


async def test_a_per_item_action_fires_once_per_item(spy):
    items = [uuid.uuid4() for _ in range(3)]
    node = _action("a", "send_webhook", url="https://x", **{ARITY_PARAM: NodeArity.ITEM.value})
    await _walk([TRIGGER, node], [Edge("t", NodePort.OUT.value, "a")], items)

    assert [call["item"] for call in spy] == items
    # Each invocation speaks for ITS item, so `{{items.keys}}` in a per-item
    # webhook names one issue rather than all of them.
    assert [call["scope"] for call in spy] == [[i] for i in items]


async def test_a_set_action_fires_once_for_many_items(spy):
    items = [uuid.uuid4() for _ in range(3)]
    node = _action("a", "send_webhook", url="https://x")  # SET is its default
    await _walk([TRIGGER, node], [Edge("t", NodePort.OUT.value, "a")], items)

    assert len(spy) == 1
    assert spy[0]["item"] is None  # no single item the run is "about"
    assert spy[0]["scope"] == items  # but it speaks for all of them


async def test_a_set_action_over_exactly_one_item_still_gets_that_item(spy):
    """What makes `{{item.key}}` resolve on an ordinary event-triggered run. The
    graph executor passed `item=None` to every universal action, so the token the
    editor offers — and the create-item form suggests as a title — rendered as
    literal braces on every automation anyone wrote."""
    item_id = uuid.uuid4()
    node = _action("a", "create_item", project="TD", title="Follow up on {{item.key}}")
    await _walk([TRIGGER, node], [Edge("t", NodePort.OUT.value, "a")], [item_id])

    assert spy[0]["item"] == item_id


async def test_a_per_item_action_is_metered_by_the_budget(spy, monkeypatch):
    """Only the ten item-mutating actions used to consume budget, because they
    were the only ones that could fan out. A per-item webhook would otherwise be
    the one unbounded thing in the engine."""
    monkeypatch.setattr(executor.settings, "automation_graph_max_item_actions", 2)
    node = _action("a", "send_webhook", url="https://x", **{ARITY_PARAM: NodeArity.ITEM.value})
    report = await _walk(
        [TRIGGER, node], [Edge("t", NodePort.OUT.value, "a")], [uuid.uuid4() for _ in range(5)]
    )

    assert len(spy) == 2
    assert report.dropped and "3 of 5 items skipped" in report.dropped[0]


async def test_create_item_emits_what_it_made(spy):
    """The created issue used to be unreachable: the action emitted its INPUT and
    `_apply_plan` discarded the return, so "file a follow-up and assign it" was
    two automations and a manual step."""
    node = _action("c", "create_item", project="TD", title="x")
    follow = _action("assign", "set_assignee", assignee="a@b.c")
    edges = [Edge("t", NodePort.OUT.value, "c"), Edge("c", NodePort.CREATED.value, "assign")]
    report = await _walk([TRIGGER, node, follow], edges, [uuid.uuid4()])

    assert report.per_node["c"]["created"] == 1
    assign = [call for call in spy if call["node"] == "assign"]
    assert len(assign) == 1 and assign[0]["item"] is not None


# --- per-item routers partition ------------------------------------------------


@pytest.fixture
def classifier(monkeypatch):
    """A contributed router that answers per item, registered for the test."""

    async def plan_items(ctx):
        # Odd/even on the uuid's int, so the split is deterministic.
        return {i: ("odd" if i.int % 2 else "even") for i in ctx.packet.item_ids}

    async def plan(_ctx):
        return "even"

    spec = AutomationNodeSpec(
        key="test.split",
        kind="gate",
        label="Split",
        ports_for=lambda _p: ("odd", "even", "unknown"),
        needs_items=False,
        arity="set",
        arity_options=("set", "item"),
        plan=plan,
        plan_items=plan_items,
    )
    monkeypatch.setitem(registries.automation_nodes, "test.split", spec)
    return spec


async def test_a_set_arity_router_sends_everything_down_one_port(spy, classifier):
    node = Node(id="s", kind=AutomationNodeKind.GATE, type="test.split", params={})
    nodes = [TRIGGER, node, _action("o", "send_webhook", url="https://o"), _action("e", "send_webhook", url="https://e")]
    edges = [
        Edge("t", NodePort.OUT.value, "s"),
        Edge("s", "odd", "o"),
        Edge("s", "even", "e"),
    ]
    report = await _walk(nodes, edges, [uuid.uuid4() for _ in range(4)])

    assert [call["node"] for call in spy] == ["e"]
    assert report.per_node["s"] == {"in": 4, "even": 4}


async def test_a_per_item_router_partitions_across_its_ports(spy, classifier):
    """The thing a loop would have been built for. Each item leaves by its own
    answer's port — same ports, finer granularity, no back-edge, no new kind of
    node. Every port emits, including one that got nothing."""
    items = [uuid.UUID(int=n) for n in (1, 2, 3, 4, 5)]
    node = Node(
        id="s",
        kind=AutomationNodeKind.GATE,
        type="test.split",
        params={ARITY_PARAM: NodeArity.ITEM.value},
    )
    nodes = [TRIGGER, node, _action("o", "add_label", label="odd"), _action("e", "add_label", label="even")]
    edges = [
        Edge("t", NodePort.OUT.value, "s"),
        Edge("s", "odd", "o"),
        Edge("s", "even", "e"),
    ]
    report = await _walk(nodes, edges, items)

    assert report.per_node["s"] == {"in": 5, "odd": 3, "even": 2, "unknown": 0}
    assert [call["item"] for call in spy if call["node"] == "o"] == [
        uuid.UUID(int=1), uuid.UUID(int=3), uuid.UUID(int=5)
    ]
    assert [call["item"] for call in spy if call["node"] == "e"] == [
        uuid.UUID(int=2), uuid.UUID(int=4)
    ]


async def test_a_per_item_router_without_plan_items_falls_back_to_one_call_each(
    spy, monkeypatch
):
    """A plugin gets per-item routing for free. `plan_items` is the OPTIMISATION
    a node reaches for when its work is expensive — not the price of admission."""
    seen: list[tuple] = []

    async def plan(ctx):
        seen.append(ctx.packet.item_ids)
        return "even"

    spec = AutomationNodeSpec(
        key="test.simple",
        kind="gate",
        label="Simple",
        ports_for=lambda _p: ("even", "unknown"),
        needs_items=False,
        arity="set",
        arity_options=("set", "item"),
        plan=plan,
    )
    monkeypatch.setitem(registries.automation_nodes, "test.simple", spec)

    items = [uuid.uuid4() for _ in range(3)]
    node = Node(
        id="s",
        kind=AutomationNodeKind.GATE,
        type="test.simple",
        params={ARITY_PARAM: NodeArity.ITEM.value},
    )
    await _walk([TRIGGER, node], [Edge("t", NodePort.OUT.value, "s")], items)

    assert seen == [(i,) for i in items], "each call sees exactly one item"


# --- the search node, and what the API refuses to store -----------------------


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from radd.config import settings

    engine_ = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine_.dispose()


@pytest.fixture
async def admin(db):
    from radd.modules.auth.models import User
    from radd.modules.auth.types import InstanceRole

    user = User(
        email=f"arity-{uuid.uuid4().hex[:8]}@example.com",
        name="Arity Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def test_a_search_node_finds_items_the_trigger_never_named(db, admin):
    """The capability the graph did not have: every other kind NARROWS what the
    trigger handed it, so an automation's reach was bounded by the event. Only a
    schedule trigger could produce a set, via a `query` param on itself."""
    from radd.modules.automations import search
    from radd.modules.items import service as items_service
    from radd.modules.items.enums import Priority
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate

    key = f"SR{uuid.uuid4().hex[:4].upper()}"
    project = await projects_service.create_project(
        db, ProjectCreate(key=key, name="Search Test"), actor_id=admin.id
    )
    wanted = await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="Urgent thing", priority=Priority.BLOCKER),
        actor=admin,
    )
    await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="Calm thing", priority=Priority.LOW),
        actor=admin,
    )
    await db.flush()

    found = await search.find_items(db, f"project = {key} AND priority = blocker")
    assert found == [wanted.id]

    # An empty query finds NOTHING rather than everything — a half-filled form is
    # the likeliest source of one, and "every issue in the instance" is the most
    # expensive possible reading of a mistake.
    assert await search.find_items(db, "  ") == []


async def test_a_role_recipient_at_set_arity_is_refused_on_write(db, admin):
    """"Email each reporter" resolved no recipient on every multi-item run and
    skip-logged — a saved, enabled automation that had never once sent a message.
    Refused where it is written, with the fix named."""
    from radd.exceptions import ConflictError
    from radd.modules.automations import service as automations
    from radd.modules.automations.schemas import RuleCreate

    def rule(arity: str) -> RuleCreate:
        return RuleCreate(
            name=f"mail-{arity}-{uuid.uuid4().hex[:6]}",
            nodes=[
                {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "manual"}},
                {
                    "id": "m",
                    "kind": "action",
                    "type": "action.send_email",
                    "params": {"to": "reporter", "subject": "s", "body": "b", ARITY_PARAM: arity},
                },
            ],
            edges=[{"source": "t", "port": "out", "target": "m"}],
        )

    with pytest.raises(ConflictError, match="once per item"):
        await automations.create_rule(db, rule(NodeArity.SET.value), actor_id=admin.id)

    stored = await automations.create_rule(db, rule(NodeArity.ITEM.value), actor_id=admin.id)
    assert stored.id is not None


async def test_an_arity_a_node_cannot_run_is_refused_on_write(db, admin):
    """Pydantic ignores unknown params, so without this a typo'd arity would be
    stored happily and silently fall back — the editor would keep showing the
    mode that was typed and the engine would run the other one."""
    from radd.exceptions import ConflictError
    from radd.modules.automations import service as automations
    from radd.modules.automations.schemas import RuleCreate

    with pytest.raises(ConflictError, match="cannot run"):
        await automations.create_rule(
            db,
            RuleCreate(
                name=f"bad-arity-{uuid.uuid4().hex[:6]}",
                nodes=[
                    {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "manual"}},
                    {
                        "id": "a",
                        "kind": "action",
                        "type": "action.set_state",
                        "params": {"state": "Done", ARITY_PARAM: NodeArity.SET.value},
                    },
                ],
                edges=[{"source": "t", "port": "out", "target": "a"}],
            ),
            actor_id=admin.id,
        )


async def test_a_search_node_is_a_legal_graph_and_its_query_is_compiled_on_write(db, admin):
    from radd.modules.automations import service as automations
    from radd.modules.automations.schemas import RuleCreate
    from radd.modules.items.slq.errors import SlqError

    def rule(query: str) -> RuleCreate:
        return RuleCreate(
            name=f"search-{uuid.uuid4().hex[:6]}",
            nodes=[
                {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "manual"}},
                {"id": "s", "kind": "source", "type": "search.slq", "params": {"slq": query}},
                {"id": "a", "kind": "action", "type": "action.add_label", "params": {"label": "x"}},
            ],
            edges=[
                {"source": "t", "port": "out", "target": "s"},
                {"source": "s", "port": "out", "target": "a"},
            ],
        )

    stored = await automations.create_rule(db, rule("priority = high"), actor_id=admin.id)
    assert stored.id is not None

    # A query that will not compile is a 422 on the form, not an automation that
    # finds nothing at 3am.
    with pytest.raises(SlqError):
        await automations.create_rule(db, rule("priority ~~ nonsense"), actor_id=admin.id)


# --- the manual path, at the HTTP surface ------------------------------------
#
# Both endpoints below 500'd from the day spec 116 landed and no test noticed,
# because every automation test drives the service and the engine directly. The
# breakage is entirely in the ROUTER — `rule.trigger` was a column that became
# the graph, and `rules_for_trigger` started returning (automation, node_id)
# pairs that the runnable list kept validating as if they were automations. So
# these are real requests or nothing.


@pytest.fixture(scope="module")
async def manual_world():
    """COMMITTED: the app under test opens its own sessions."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from radd.config import settings
    from radd.modules.auth import service as auth_service
    from radd.modules.auth.models import User
    from radd.modules.auth.types import InstanceRole
    from radd.modules.automations import service as automations
    from radd.modules.automations.schemas import RuleCreate
    from radd.modules.items import service as items_service
    from radd.modules.items.enums import Priority
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate

    engine_ = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        admin = User(
            email=f"man-{uuid.uuid4().hex[:8]}@example.com",
            name="Manual Tester",
            instance_role=InstanceRole.ADMIN.value,
        )
        session.add(admin)
        await session.flush()
        cookie = await auth_service.create_session(session, admin)
        key = f"MN{uuid.uuid4().hex[:4].upper()}"
        project = await projects_service.create_project(
            session, ProjectCreate(key=key, name="Manual Test"), actor_id=admin.id
        )
        item = await items_service.create_item(
            session,
            ItemCreate(project_id=project.id, title="press the button", priority=Priority.BLOCKER),
            actor=admin,
        )
        rule = await automations.create_rule(
            session,
            RuleCreate(
                name=f"manual-{uuid.uuid4().hex[:6]}",
                nodes=[
                    {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "manual"}},
                    {"id": "a", "kind": "action", "type": "action.add_label", "params": {"label": "pressed"}},
                ],
                edges=[{"source": "t", "port": "out", "target": "a"}],
            ),
            actor_id=admin.id,
        )
        payload = {"cookie": cookie, "rule_id": str(rule.id), "item_id": str(item.id)}
        await session.commit()
        yield payload
    await engine_.dispose()


@pytest.fixture(scope="module")
def manual_app():
    from radd.app import create_app

    return create_app()


@pytest.fixture
async def manual_client(manual_app):
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=manual_app), base_url="http://test"
    ) as client:
        yield client


async def test_a_manual_automation_can_actually_be_run(manual_client, manual_world):
    """POST /automations/{id}/run raised AttributeError on `rule.trigger` — a
    column spec 116 replaced with the graph. The editor's `/` quick-action menu
    is the only caller, so every custom action 500'd."""
    from radd.modules.auth.types import SESSION_COOKIE_NAME

    cookies = {SESSION_COOKIE_NAME: manual_world["cookie"]}
    response = await manual_client.post(
        f"/api/v1/automations/{manual_world['rule_id']}/run",
        json={"item_id": manual_world["item_id"]},
        cookies=cookies,
    )
    assert response.status_code == 200, response.text
    assert response.json()["ran"] is True

    item = await manual_client.get(f"/api/v1/items/{manual_world['item_id']}", cookies=cookies)
    assert "pressed" in item.json()["labels"]


async def test_the_runnable_list_returns_automations_not_tuples(manual_client, manual_world):
    """`rules_for_trigger` returns (automation, node_id) since a graph may hold
    several triggers; the list validated the pair as if it were the automation."""
    from radd.modules.auth.types import SESSION_COOKIE_NAME

    response = await manual_client.get(
        "/api/v1/automations/runnable", cookies={SESSION_COOKIE_NAME: manual_world["cookie"]}
    )
    assert response.status_code == 200, response.text
    assert any(row["id"] == manual_world["rule_id"] for row in response.json())


async def test_an_automation_with_no_manual_trigger_is_refused_not_run(manual_client, manual_world):
    """A 409 naming the reason, rather than running the Monday branch because it
    happened to be the graph's first trigger."""
    from radd.modules.auth.types import SESSION_COOKIE_NAME

    cookies = {SESSION_COOKIE_NAME: manual_world["cookie"]}
    created = await manual_client.post(
        "/api/v1/automations",
        json={
            "name": f"not-manual-{uuid.uuid4().hex[:6]}",
            "nodes": [
                {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.updated"}},
                {"id": "a", "kind": "action", "type": "action.add_label", "params": {"label": "x"}},
            ],
            "edges": [{"source": "t", "port": "out", "target": "a"}],
        },
        cookies=cookies,
    )
    assert created.status_code == 201, created.text
    response = await manual_client.post(
        f"/api/v1/automations/{created.json()['id']}/run",
        json={"item_id": manual_world["item_id"]},
        cookies=cookies,
    )
    assert response.status_code == 409
    await manual_client.delete(f"/api/v1/automations/{created.json()['id']}", cookies=cookies)
