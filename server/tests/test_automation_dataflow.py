"""Automation dataflow: named node outputs and the packet variable bag (spec 120).

Before this an automation graph could route on what a node decided and never
READ it. `ai.classify` picked "Bug" out of four answers, sent the packet down the
Bug branch — and the only way to act on that was a hardcoded action per branch.
The value the model produced existed for one instant inside the executor.

What these pin is the part that is easy to get subtly wrong, which is not the
happy path:

* the bag is a property of the PACKET, so a value produced on one branch is not
  readable on a branch that never ran;
* fan-in merges in TOPOLOGICAL order, so "the later producer wins" means the one
  that actually ran second rather than whichever edge was stored first;
* a per-item run produces N answers and publishes none of them, because the bag
  has one slot per node and picking one silently would be a wrong write;
* the write path refuses a token naming a node that is not there — the failure
  mode this whole spec is about is an action that quietly does not happen.
"""

import uuid

import pytest

from radd.kernel.registry import registries
from radd.kernel.specs import AutomationNodeSpec, OutputField, OutputKind, valid_output_name
from radd.modules.automations import executor, graph, nodes as nodes_registry, templating
from radd.modules.automations.conditions import EventFacts
from radd.modules.automations.graph import Edge, Node, Packet
from radd.modules.automations.types import AutomationNodeKind


FACTS = EventFacts(
    event_type="item.created", actor_id=None, actor_email=None, actor_name=None, payload={}
)

TRIGGER = Node(id="t", kind=AutomationNodeKind.TRIGGER, type="trigger.event", params={})


class _Item:
    def __init__(self, item_id: uuid.UUID):
        self.id = item_id


class _Savepoints:
    """Just enough session for `_one`, which wraps every invocation in one."""

    def begin_nested(self):
        class _Scope:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *_exc):
                return False

        return _Scope()


# --- the bag itself -----------------------------------------------------------


def test_the_bag_rides_on_the_packet_and_writes_never_mutate_a_shared_one():
    """Every write rebuilds the outer mapping, so a packet handed to three
    downstream nodes cannot be edited from under them by a fourth."""
    base = Packet.of(FACTS, item=())
    first = base.with_vars("triage", {"priority": "high"})
    second = first.with_vars("summary", {"text": "a sentence"})

    assert base.vars == {}, "the original is untouched"
    assert first.vars == {"triage": {"priority": "high"}}
    assert second.vars["triage"] == {"priority": "high"}
    assert second.vars["summary"] == {"text": "a sentence"}
    # The inner mappings are SHARED, which is safe because nothing mutates one.
    assert first.vars["triage"] is second.vars["triage"]


def test_values_are_stringified_at_the_seam():
    """A producer hands over whatever it has; a token renders to text. Coercing
    once here beats every consumer guessing."""
    packet = Packet.of(FACTS).with_vars("n", {"count": 7, "flag": True})
    assert packet.vars["n"] == {"count": "7", "flag": "True"}


def test_an_unnamed_producer_is_not_addressable():
    """Filing its values under the node ID would invent `{{act3.key}}` — a token
    nobody wrote and nothing offers."""
    assert Packet.of(FACTS).with_vars("", {"key": "TD-1"}).vars == {}


def test_subject_edits_carry_the_bag():
    """A filter narrows items; it must not lose what an upstream node produced."""
    packet = Packet.of(FACTS, item=(uuid.uuid4(),)).with_vars("triage", {"priority": "high"})
    assert packet.with_items(()).vars == {"triage": {"priority": "high"}}


def test_merge_unions_with_the_later_writer_winning():
    left = Packet.of(FACTS).with_vars("a", {"x": "1"})
    right = Packet.of(FACTS).with_vars("a", {"x": "2"}).with_vars("b", {"y": "3"})
    assert left.merge(right).vars == {"a": {"x": "2"}, "b": {"y": "3"}}


# --- the walk -----------------------------------------------------------------


def _gate_spec(key: str, produced: dict[str, str], *, arity: str = "set", ports=("out",)):
    """A contributed router that publishes `produced` and takes its first port."""

    async def plan(ctx):
        for name, value in produced.items():
            ctx.set_output(name, value)
        return ports[0]

    return AutomationNodeSpec(
        key=key,
        kind="gate",
        label=key,
        ports=tuple(ports),
        outputs=tuple(OutputField(name=name) for name in produced),
        needs_items=False,
        arity=arity,
        arity_options=("set", "item") if arity == "item" else (),
        plan=plan,
    )


@pytest.fixture
def registered():
    """Register node specs for one test and take them out again."""
    added: list[str] = []

    def register(spec):
        registries.automation_nodes[spec.key] = spec
        added.append(spec.key)
        return spec

    yield register
    for key in added:
        registries.automation_nodes.pop(key, None)


async def _walk(nodes, edges, item_ids=(), apply=True):
    return await executor.walk(
        None,
        nodes=nodes,
        edges=edges,
        trigger=TRIGGER,
        initial=Packet.of(FACTS, item=tuple(item_ids)),
        system_user=object(),
        automation_name="dataflow test",
        budget=executor.new_budget(),
        apply=apply,
    )


async def test_a_named_producer_stamps_the_bag_and_an_action_reads_it(registered, monkeypatch):
    """The whole feature in one graph: a node produces, a downstream action's
    params render from what it produced."""
    registered(_gate_spec("test.produce", {"priority": "high"}))
    producer = Node(
        id="p", kind=AutomationNodeKind.GATE, type="test.produce", params={}, name="triage"
    )
    action = Node(
        id="a",
        kind=AutomationNodeKind.ACTION,
        type="action.set_priority",
        params={"priority": "{{triage.priority}}"},
    )

    seen: list[dict] = []

    async def fake_load(_session, item_ids):
        return [(_Item(i), object()) for i in item_ids]

    async def fake_one(
        _session, node, stored, item, _project, _actor, packet, _scope, _name, _apply, _report
    ):
        seen.append({"node": node.id, "vars": dict(packet.vars)})
        return executor._Outcome()

    monkeypatch.setattr(executor, "_load", fake_load)
    monkeypatch.setattr(executor, "_one", fake_one)

    item = uuid.uuid4()
    report = await _walk(
        [TRIGGER, producer, action],
        [Edge("t", "out", "p"), Edge("p", "out", "a")],
        item_ids=(item,),
    )

    assert seen == [{"node": "a", "vars": {"triage": {"priority": "high"}}}]
    # Recorded for the dry run whether or not anyone reads it.
    assert report.produced == {"p": {"priority": "high"}}


async def test_an_unnamed_producer_still_runs_and_still_reports(registered, monkeypatch):
    """It is unaddressable, not broken — and the dry run says what it made, which
    is how someone discovers they forgot to name it."""
    registered(_gate_spec("test.produce", {"priority": "high"}))
    producer = Node(id="p", kind=AutomationNodeKind.GATE, type="test.produce", params={})

    async def fake_load(_session, item_ids):
        return [(_Item(i), object()) for i in item_ids]

    monkeypatch.setattr(executor, "_load", fake_load)
    report = await _walk([TRIGGER, producer], [Edge("t", "out", "p")], item_ids=(uuid.uuid4(),))
    assert report.produced == {"p": {"priority": "high"}}


async def test_a_per_item_producer_publishes_nothing(registered, monkeypatch):
    """N items, N answers, one slot. Publishing one of them would let
    `{{classify.answer}}` silently name whichever item came last."""
    registered(
        _gate_spec("test.per_item", {"answer": "Bug"}, arity="item", ports=("out", "other"))
    )
    producer = Node(
        id="p",
        kind=AutomationNodeKind.GATE,
        type="test.per_item",
        params={"arity": "item"},
        name="classify",
    )

    async def fake_load(_session, item_ids):
        return [(_Item(i), object()) for i in item_ids]

    monkeypatch.setattr(executor, "_load", fake_load)
    report = await _walk(
        [TRIGGER, producer], [Edge("t", "out", "p")], item_ids=(uuid.uuid4(), uuid.uuid4())
    )
    assert report.produced == {}


async def test_the_bag_does_not_leak_onto_a_branch_that_never_ran(registered, monkeypatch):
    """A gate emits ONE port. The node on the other one never sees the values,
    which is the whole reason the bag rides on the packet rather than on the run."""
    registered(_gate_spec("test.route", {"answer": "yes"}, ports=("taken", "untaken")))
    router = Node(
        id="r", kind=AutomationNodeKind.GATE, type="test.route", params={}, name="ask"
    )
    took = Node(id="a1", kind=AutomationNodeKind.ACTION, type="action.add_label", params={})
    missed = Node(id="a2", kind=AutomationNodeKind.ACTION, type="action.add_label", params={})

    seen: dict[str, dict] = {}

    async def fake_load(_session, item_ids):
        return [(_Item(i), object()) for i in item_ids]

    async def fake_one(
        _session, node, _stored, _item, _project, _actor, packet, _scope, _name, _apply, _report
    ):
        seen[node.id] = dict(packet.vars)
        return executor._Outcome()

    monkeypatch.setattr(executor, "_load", fake_load)
    monkeypatch.setattr(executor, "_one", fake_one)

    await _walk(
        [TRIGGER, router, took, missed],
        [
            Edge("t", "out", "r"),
            Edge("r", "taken", "a1"),
            Edge("r", "untaken", "a2"),
        ],
        item_ids=(uuid.uuid4(),),
    )

    assert seen == {"a1": {"ask": {"answer": "yes"}}}, "the untaken branch never ran at all"


async def test_fan_in_merges_feeders_in_topological_order(registered, monkeypatch):
    """Deterministic by the ORDER THINGS RAN, not by the order edges were stored.

    The edges here are deliberately listed with the later producer FIRST, which
    is what a naive merge would honour — and would then flip the answer the next
    time someone dragged the wires in a different sequence."""
    registered(_gate_spec("test.first", {"who": "first"}))
    registered(_gate_spec("test.second", {"who": "second"}))
    first = Node(id="p1", kind=AutomationNodeKind.GATE, type="test.first", params={}, name="v")
    second = Node(id="p2", kind=AutomationNodeKind.GATE, type="test.second", params={}, name="v")
    sink = Node(id="a", kind=AutomationNodeKind.ACTION, type="action.add_label", params={})

    seen: list[dict] = []

    async def fake_load(_session, item_ids):
        return [(_Item(i), object()) for i in item_ids]

    async def fake_one(
        _session, _node, _stored, _item, _project, _actor, packet, _scope, _name, _apply, _report
    ):
        seen.append(dict(packet.vars))
        return executor._Outcome()

    monkeypatch.setattr(executor, "_load", fake_load)
    monkeypatch.setattr(executor, "_one", fake_one)

    await _walk(
        [TRIGGER, first, second, sink],
        [
            Edge("t", "out", "p1"),
            Edge("t", "out", "p2"),
            # Stored later-first on purpose.
            Edge("p2", "out", "a"),
            Edge("p1", "out", "a"),
        ],
        item_ids=(uuid.uuid4(),),
    )

    assert seen == [{"v": {"who": "second"}}], "p2 ran second, so p2's value survives"


# --- the seam a contributed node writes through -------------------------------


def test_set_output_refuses_a_name_nothing_could_reference():
    """A value filed under `Answer!` could never appear in `{{…}}`, so storing it
    would only put an unreachable row in the run report."""
    ctx = executor._NodeContext(
        session=None, node=TRIGGER, packet=Packet.of(FACTS), actor=object()
    )
    ctx.set_output("answer", "Bug")
    ctx.set_output("Answer!", "Bug")
    ctx.set_output("", "Bug")
    assert ctx.outputs == {"answer": "Bug"}


def test_the_name_rule_is_the_kernel_s_and_covers_both_halves_of_a_token():
    assert valid_output_name("triage")
    assert valid_output_name("triage_2")
    assert not valid_output_name("Triage")
    assert not valid_output_name("2triage")
    assert not valid_output_name("triage.priority"), "a dot is the separator"
    assert not valid_output_name("a" * 31)


# --- the declarations ---------------------------------------------------------


def test_outputs_rank_static_over_dynamic_exactly_as_ports_do():
    spec = AutomationNodeSpec(
        key="k",
        kind="gate",
        label="k",
        outputs=(OutputField(name="fixed"),),
        outputs_for=lambda _p: (OutputField(name="dynamic"),),
    )
    assert [f.name for f in spec.outputs_at({})] == ["fixed"]

    dynamic = AutomationNodeSpec(
        key="k", kind="gate", label="k", outputs_for=lambda p: (OutputField(name=p["n"]),)
    )
    assert [f.name for f in dynamic.outputs_at({"n": "typed"})] == ["typed"]


def test_a_node_type_that_produces_nothing_says_so():
    """The honest default. A fallback that invented outputs would put tokens in
    the editor's picker that can never resolve."""
    assert nodes_registry.outputs_of(TRIGGER) == ()
    filter_node = Node(id="f", kind=AutomationNodeKind.FILTER, type="filter.slq", params={})
    assert nodes_registry.outputs_of(filter_node) == ()


def test_create_item_declares_the_key_of_what_it_made():
    node = Node(
        id="c", kind=AutomationNodeKind.ACTION, type="action.create_item", params={}
    )
    assert [f.name for f in nodes_registry.outputs_of(node)] == ["key", "id", "url"]


def test_the_classifier_declares_its_answers_as_an_enum():
    from radd.modules.ai import automation_node as classify

    fields = classify.outputs_for({"answers": ["Bug", "Feature"]})
    assert [f.name for f in fields] == ["answer"]
    assert fields[0].kind == OutputKind.ENUM.value
    assert fields[0].choices == ("Bug", "Feature")


def test_reserved_roots_are_derived_from_the_token_catalogue():
    """Not hand-listed: a root that stopped being reserved would let someone name
    a node `item` and shadow `{{item.key}}` everywhere in the graph."""
    roots = templating.reserved_roots()
    assert {"item", "items", "actor", "payload", "event_type", "matched_count"} <= roots
    for token in templating.TOKENS:
        assert token.token.strip("{} ").split(".", 1)[0] in roots


# --- what the API refuses to store --------------------------------------------


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
        email=f"dataflow-{uuid.uuid4().hex[:8]}@example.com",
        name="Dataflow Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


def _rule(name: str, nodes: list[dict], edges: list[dict] | None = None):
    from radd.modules.automations.schemas import RuleCreate

    return RuleCreate(name=name, nodes=nodes, edges=edges or [])


def _trigger_dict(**extra):
    return {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "manual"}, **extra}


def _create_item_dict(**extra):
    return {
        "id": "c",
        "kind": "action",
        "type": "action.create_item",
        "params": {"project": "TD", "title": "x"},
        **extra,
    }


async def test_a_name_that_cannot_appear_in_a_token_is_refused(db, admin):
    from radd.exceptions import ConflictError
    from radd.modules.automations import service as automations

    with pytest.raises(ConflictError) as caught:
        await automations.create_rule(
            db,
            _rule("bad name", [_trigger_dict(), _create_item_dict(name="Triage Result")]),
            actor_id=admin.id,
        )
    assert "not a usable name" in str(caught.value)


async def test_two_nodes_cannot_share_a_name(db, admin):
    from radd.exceptions import ConflictError
    from radd.modules.automations import service as automations

    with pytest.raises(ConflictError) as caught:
        await automations.create_rule(
            db,
            _rule(
                "dup",
                [
                    _trigger_dict(),
                    _create_item_dict(name="followup"),
                    {**_create_item_dict(), "id": "c2", "name": "followup"},
                ],
            ),
            actor_id=admin.id,
        )
    assert "could only mean one of them" in str(caught.value)


async def test_a_node_may_not_shadow_a_template_word(db, admin):
    """`{{item.key}}` would keep resolving — just to something else."""
    from radd.exceptions import ConflictError
    from radd.modules.automations import service as automations

    with pytest.raises(ConflictError) as caught:
        await automations.create_rule(
            db, _rule("shadow", [_trigger_dict(), _create_item_dict(name="item")]), actor_id=admin.id
        )
    assert "already a template word" in str(caught.value)


async def test_a_token_naming_a_node_that_is_not_there_is_refused(db, admin):
    """The failure this spec is about: rename the producer, leave the consumer
    behind, and the action quietly stops happening at 3am."""
    from radd.exceptions import ConflictError
    from radd.modules.automations import service as automations

    with pytest.raises(ConflictError) as caught:
        await automations.create_rule(
            db,
            _rule(
                "dangling",
                [
                    _trigger_dict(),
                    {
                        "id": "a",
                        "kind": "action",
                        "type": "action.add_comment",
                        "params": {"body": "priority is {{triage.priority}}"},
                    },
                ],
            ),
            actor_id=admin.id,
        )
    message = str(caught.value)
    assert "{{triage.priority}}" in message and "'triage'" in message


async def test_a_token_naming_an_output_its_producer_cannot_make_is_refused(db, admin):
    """A producer that DECLARED its outputs is measured against them. One that
    declared none accepts anything — punishing a plugin's user for the plugin's
    silence would be the wrong way round."""
    from radd.exceptions import ConflictError
    from radd.modules.automations import service as automations

    with pytest.raises(ConflictError) as caught:
        await automations.create_rule(
            db,
            _rule(
                "wrong field",
                [
                    _trigger_dict(),
                    _create_item_dict(name="followup"),
                    {
                        "id": "a",
                        "kind": "action",
                        "type": "action.add_comment",
                        "params": {"body": "filed {{followup.number}}"},
                    },
                ],
                [{"source": "t", "port": "out", "target": "c"}, {"source": "c", "port": "out", "target": "a"}],
            ),
            actor_id=admin.id,
        )
    assert "produces id, key, url" in str(caught.value)


async def test_a_well_formed_reference_saves_and_round_trips(db, admin):
    from radd.modules.automations import service as automations

    rule = await automations.create_rule(
        db,
        _rule(
            "good",
            [
                _trigger_dict(),
                _create_item_dict(name="followup"),
                {
                    "id": "a",
                    "kind": "action",
                    "type": "action.add_comment",
                    "params": {"body": "filed {{followup.key}}"},
                },
            ],
            [
                {"source": "t", "port": "out", "target": "c"},
                {"source": "c", "port": "created", "target": "a"},
            ],
        ),
        actor_id=admin.id,
    )
    stored = {node["id"]: node for node in rule.nodes}
    assert stored["c"]["name"] == "followup", "the name is stored, not dropped by the envelope"


# --- resolution: what a token becomes, and what happens when it becomes nothing ---


async def _fixture_project(db, admin, key_prefix="DF"):
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate

    key = f"{key_prefix}{uuid.uuid4().hex[:4].upper()}"
    return await projects_service.create_project(
        db, ProjectCreate(key=key, name="Dataflow"), actor_id=admin.id
    )


async def _fixture_item(db, admin, project):
    """The item ROW (not the read model) — what the planner is handed."""
    from radd.modules.items import service as items_service
    from radd.modules.items.models import WorkItem
    from radd.modules.items.schemas import ItemCreate

    read = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="A thing"), actor=admin
    )
    await db.flush()
    return await db.get(WorkItem, read.id)


async def test_a_tokenized_priority_resolves_through_the_existing_by_name_seam(db, admin):
    """The flagship: the model said "high", the action sets high. Nothing about
    the RESOLUTION changed — the value is rendered first, then goes through the
    same enum coercion a literal always did."""
    from radd.modules.automations.planning import _plan
    from radd.modules.automations.types import PlanKind
    from radd.modules.items.enums import Priority

    project = await _fixture_project(db, admin)
    item = await _fixture_item(db, admin, project)

    plan = await _plan(
        db,
        {"type": "set_priority", "params": {"priority": "{{triage.priority}}"}},
        item,
        project,
        admin,
        facts=FACTS,
        rule_name="t",
        variables={"triage": {"priority": "high"}},
    )
    assert plan.kind is PlanKind.ITEM_UPDATE
    assert plan.item_update.priority is Priority.HIGH
    assert plan.resolved == {"{{triage.priority}}": "high"}


async def test_a_token_that_found_nothing_skips_the_action_with_the_reason(db, admin):
    """The `unavailable` branch of an AI node: the values were never produced, so
    the actions that needed them must not happen — and must say why."""
    from radd.modules.automations.planning import _plan
    from radd.modules.automations.types import PlanKind

    project = await _fixture_project(db, admin)
    plan = await _plan(
        db,
        {"type": "set_priority", "params": {"priority": "{{triage.priority}}"}},
        None,
        project,
        admin,
        facts=FACTS,
        rule_name="t",
        variables={},
    )
    assert plan.kind is PlanKind.SKIP
    assert "{{triage.priority}}" in plan.detail
    assert "no node named 'triage'" in plan.detail


async def test_a_token_naming_a_field_the_producer_did_not_make_names_what_it_did(db, admin):
    from radd.modules.automations.planning import _plan
    from radd.modules.automations.types import PlanKind

    project = await _fixture_project(db, admin)
    plan = await _plan(
        db,
        {"type": "set_priority", "params": {"priority": "{{triage.urgency}}"}},
        None,
        project,
        admin,
        facts=FACTS,
        rule_name="t",
        variables={"triage": {"priority": "high", "team": "Support"}},
    )
    assert plan.kind is PlanKind.SKIP
    assert "produced priority, team, not 'urgency'" in plan.detail


async def test_a_rendered_value_outside_the_vocabulary_skips_and_lists_it(db, admin):
    """The model answered something real and wrong. The skip names what WOULD
    have worked, from the list the planner already had — never a second query."""
    from radd.modules.automations.planning import _plan
    from radd.modules.automations.types import PlanKind

    project = await _fixture_project(db, admin)
    item = await _fixture_item(db, admin, project)

    priority = await _plan(
        db,
        {"type": "set_priority", "params": {"priority": "{{triage.priority}}"}},
        item,
        project,
        admin,
        facts=FACTS,
        rule_name="t",
        variables={"triage": {"priority": "urgent"}},
    )
    assert priority.kind is PlanKind.SKIP
    assert "'urgent' is not a priority" in priority.detail
    assert "blocker" in priority.detail, "the vocabulary is spelled out"

    state = await _plan(
        db,
        {"type": "set_state", "params": {"state": "{{triage.state}}"}},
        item,
        project,
        admin,
        facts=FACTS,
        rule_name="t",
        variables={"triage": {"state": "Blocked"}},
    )
    assert state.kind is PlanKind.SKIP
    assert "no state 'Blocked'" in state.detail
    assert "states: " in state.detail, "and it comes from the list already fetched"


async def test_an_unknown_payload_token_still_degrades_verbatim(db, admin):
    """The pre-existing contract, deliberately untouched. A payload path an event
    does not carry is a normal miss on a shape that varies per event, and turning
    it into a skip would silently disable working automations."""
    from radd.modules.automations.planning import _plan
    from radd.modules.automations.types import PlanKind

    project = await _fixture_project(db, admin)
    item = await _fixture_item(db, admin, project)

    plan = await _plan(
        db,
        {"type": "add_comment", "params": {"body": "was {{payload.nope}}", "visibility": "public"}},
        item,
        project,
        admin,
        facts=FACTS,
        rule_name="t",
        variables={},
    )
    assert plan.kind is PlanKind.COMMENT
    assert plan.comment.body == "was {{payload.nope}}"


async def test_a_workflow_guard_refusal_becomes_a_recorded_skip(monkeypatch):
    """It is not an engine failure and it is not a bug: the project's transition
    rules apply to automations too, deliberately. What was wrong is that it landed
    in the generic `except Exception` — logged as a crash, and reported by the dry
    run as an action that "would apply" and never could."""
    from radd.modules.automations import engine, planning
    from radd.modules.automations.planning import _Plan
    from radd.modules.automations.types import PlanKind
    from radd.modules.workflow.guards import TransitionError

    async def refuse(*_args, **_kwargs):
        raise TransitionError(["the estimate is required"], "Todo", "Done")

    async def planned(*_args, **_kwargs):
        return _Plan(PlanKind.ITEM_UPDATE, "set_state -> 'Done'")

    monkeypatch.setattr(engine, "_apply_plan", refuse)
    monkeypatch.setattr(planning, "_plan", planned)

    report = executor.RunReport()
    node = Node(id="a", kind=AutomationNodeKind.ACTION, type="action.set_state", params={})
    outcome = await executor._one(
        _Savepoints(), node, {"type": "set_state", "params": {}}, _Item(uuid.uuid4()), object(),
        object(), Packet.of(FACTS), [], "guarded", True, report,
    )

    assert outcome.created_id is None
    assert len(report.plans) == 1, "one record per invocation, not two that contradict"
    assert report.plans[0].resolves is False
    assert "refused by the workflow: the estimate is required" in report.plans[0].detail
    assert "from Todo to Done" in report.plans[0].detail
