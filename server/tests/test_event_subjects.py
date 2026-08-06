"""The contribution seam: kernel-owned subjects, plugin-owned data and behaviour
(RADD-923).

RADD-922 unified fourteen hand-built payload shapes and left an AST test to keep
them unified — a test only necessary because the shape was still hand-built. This
deletes the failure mode instead: an emitter passes IDS and the kernel writes the
ref, so it cannot write a different one.

The other half is symmetry. A plugin could contribute an event and a gate but not
an ACTION: `executor._run_action` did `ActionType(node.type)`, which raises for
anything outside the built-in enum, logged "unknown action type", and dropped the
node. So a plugin could say "when my deployment finishes" and "if the AI thinks
it's risky", and never "…then do my thing".

The milestones plugin is the acceptance test for both, because it is the only one
that adds a whole feature from one directory.
"""

from __future__ import annotations

import uuid

import pytest

from radd.kernel.registry import registries
from radd.kernel.specs import AutomationNodeSpec, EntityRefSpec, EventTypeSpec
from radd.modules.automations import executor
from radd.modules.automations.conditions import EventFacts
from radd.modules.automations.graph import Edge, Node, Packet
from radd.modules.automations.types import AutomationNodeKind, NodePort


# --- fixtures ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _load_milestones(_kernel_registries_loaded):
    """Milestones is a non-core plugin — it ships in the repo but is runtime
    enabled, so the builtin bootstrap does not load it. Loading it here is
    literally the north-star's "drop in the plugin", and the point of this file
    is that dropping it in is all a plugin has to do."""
    from radd.kernel import entities as kentities
    from radd.modules.milestones import plugin as milestones_plugin

    registries.register_plugin(milestones_plugin)
    for spec in milestones_plugin.entities:
        kentities.register_entity(spec)
    yield


class _StubSession:
    """Enough session for the executor's savepoint. The contributed-action tests
    are about the CONTAINMENT — budget, savepoint, plan/apply split — and a real
    database would only make a failure harder to read."""

    def begin_nested(self):
        class _Savepoint:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *_exc):
                return False

        return _Savepoint()


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
async def world(db):
    """A real project + item, so the ref resolves against real joins."""
    from radd.modules.auth.models import User
    from radd.modules.auth.types import InstanceRole
    from radd.modules.items import service as items_service
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate

    admin = User(
        email=f"subj-{uuid.uuid4().hex[:8]}@example.com",
        name="Subject Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    key = f"SB{uuid.uuid4().hex[:4].upper()}"
    project = await projects_service.create_project(
        db, ProjectCreate(key=key, name="Subjects"), actor_id=admin.id
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="subject check"), actor=admin
    )
    await db.flush()
    return {
        "item_id": item.id,
        "item_key": item.key,
        "project_key": key,
        "admin": admin,
    }


# --- the kernel owns the shape ------------------------------------------------


def test_the_spine_entities_all_describe_themselves():
    """`item`, `project` and every declared plugin entity. A subject with no ref
    is an automation that silently does nothing, so the loader refuses it — but
    only if these are actually registered."""
    for entity_type in ("item", "project", "milestone"):
        assert entity_type in registries.entity_refs, f"{entity_type} has no EntityRefSpec"


def test_a_declared_entity_gets_its_ref_and_its_subject_for_free():
    """The north-star property. `milestones/spec.py` declares five FIELDS and no
    events, no refs and no payload shape — and its events carry a real ref."""
    assert registries.event_types["milestone.created"].subjects == ("milestone",)
    assert registries.entity_refs["milestone"].ref is not None


async def test_emit_writes_the_ref_from_an_id(db, world):
    """The whole point: the emitter passes an ID. Fourteen emitters used to build
    this dict, which is how fourteen shapes happened."""
    from radd.modules.events import service as events
    from radd.modules.events.models import Event
    from sqlalchemy import select

    await events.emit(
        db,
        event_type="item.updated",
        entity_type="item",
        entity_id=world["item_id"],
        subjects={"item": world["item_id"]},
        payload={"mine": "own data"},
    )
    await db.flush()
    row = (
        await db.execute(select(Event).order_by(Event.id.desc()).limit(1))
    ).scalar_one()

    assert row.payload["item"]["key"] == world["item_key"]
    assert row.payload["item"]["project"]["key"] == world["project_key"]
    assert row.payload["item"]["state"]["category"]
    assert row.payload["mine"] == "own data", "the plugin's own data is untouched"


async def test_a_none_subject_is_recorded_as_none_not_omitted(db):
    """A comment on a PAGE has no item. `None` says so; omitting the key would
    make "not an item" and "the emitter forgot" the same thing."""
    from radd.modules.events import service as events

    payload = await events._with_subjects(db, {"x": 1}, {"item": None})
    assert payload == {"x": 1, "item": None}


async def test_a_key_collision_fails_loudly(db, world):
    """A plugin's own `payload["item"]` versus the subject ref of the same name.
    Somebody is about to read the wrong thing, so it fails where it can still be
    fixed rather than silently resolving one way."""
    from radd.modules.events import service as events

    with pytest.raises(RuntimeError, match="collides"):
        await events._with_subjects(db, {"item": "mine"}, {"item": world["item_id"]})


def test_the_loader_refuses_a_subject_nothing_describes():
    """Boot is the cheapest place to find this. The alternative is an automation
    that saves cleanly, enables cleanly, and does nothing at 3am."""
    from radd.kernel.loader import PluginLoadError, _check_subjects
    from radd.kernel.plugin import RaddPlugin

    broken = RaddPlugin(
        name="broken",
        event_types=(
            EventTypeSpec("deploy.finished", "Deployed", "Deploys", subjects=("deployment",)),
        ),
    )
    with pytest.raises(PluginLoadError, match="deployment"):
        _check_subjects([broken])


def test_the_loader_refuses_an_action_acting_on_nothing():
    from radd.kernel.loader import PluginLoadError, _check_subjects
    from radd.kernel.plugin import RaddPlugin

    broken = RaddPlugin(
        name="broken",
        automation_nodes=(
            AutomationNodeSpec(key="x.act", kind="action", label="X", subject="widget"),
        ),
    )
    with pytest.raises(PluginLoadError, match="widget"):
        _check_subjects([broken])


# --- the packet carries every subject -----------------------------------------


def test_a_packet_holds_more_than_items():
    """An event about a deployment names the deployment, the release AND the
    item; a node declaring `subject="release"` must be able to get the release."""
    release, item = uuid.uuid4(), uuid.uuid4()
    packet = Packet.of(None, item=[item], release=[release])

    assert packet.item_ids == (item,)
    assert packet.ids_of("release") == (release,)
    assert packet.ids_of("nothing") == ()


def test_narrowing_one_subject_keeps_the_others():
    """A filter narrows the ITEMS an event is about without forgetting which
    release it was about."""
    release, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    packet = Packet.of(None, item=[a, b], release=[release]).with_items([a])

    assert packet.item_ids == (a,)
    assert packet.ids_of("release") == (release,)


def test_fan_in_merges_per_subject_and_dedupes():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    left = Packet.of(None, item=[a, b], release=[c])
    right = Packet.of(None, item=[b], milestone=[c])
    merged = left.merge(right)

    assert merged.item_ids == (a, b)
    assert merged.ids_of("release") == (c,)
    assert merged.ids_of("milestone") == (c,)


def test_the_engine_seeds_every_subject_the_event_carries():
    """`apply_event` reads the refs back out of the payload, so a plugin's own
    entity reaches the packet with no automations code knowing it exists."""
    from radd.modules.automations.engine import _subjects_of

    milestone_id, item_id = uuid.uuid4(), uuid.uuid4()

    class _Event:
        payload = {
            "milestone": {"id": str(milestone_id), "title": "M1"},
            "item": {"id": str(item_id)},
            "environment": "prod",  # the plugin's own data — not a subject
        }

    found = _subjects_of(_Event())
    assert found["milestone"] == (milestone_id,)
    assert found["item"] == (item_id,)
    assert "environment" not in found


# --- a contributed ACTION runs, and is contained -------------------------------


FACTS = EventFacts(
    event_type="milestone.created", actor_id=None, actor_email=None, actor_name=None, payload={}
)
TRIGGER = Node(id="t", kind=AutomationNodeKind.TRIGGER, type="trigger.event", params={})


@pytest.fixture
def plugin_action(monkeypatch):
    """A plugin action on a NON-item subject, registered for the test."""
    calls: dict[str, list] = {"planned": [], "applied": []}

    class _Plan:
        def __init__(self, ids):
            self.ids = ids
            self.detail = f"would act on {len(ids)}"
            self.resolves = bool(ids)

    async def plan(ctx):
        calls["planned"].append(tuple(ctx.subject_ids))
        return _Plan(tuple(ctx.subject_ids))

    async def apply(ctx, plan):
        calls["applied"].append(plan.ids)

    monkeypatch.setitem(
        registries.entity_refs, "widget", EntityRefSpec("widget", lambda *_: None)
    )
    monkeypatch.setitem(
        registries.automation_nodes,
        "widget.poke",
        AutomationNodeSpec(
            key="widget.poke", kind="action", label="Poke",
            subject="widget", arity="item", needs_items=False,
            plan=plan, apply=apply,
        ),
    )
    return calls


async def _walk(nodes, edges, packet, *, apply=True):
    return await executor.walk(
        _StubSession(),
        nodes=nodes,
        edges=edges,
        trigger=TRIGGER,
        initial=packet,
        system_user=object(),
        automation_name="test",
        budget=executor.new_budget(),
        apply=apply,
    )


async def test_a_contributed_action_actually_runs(plugin_action):
    """It used to be dropped with "unknown action type" — declarable and dead."""
    widgets = [uuid.uuid4(), uuid.uuid4()]
    node = Node(id="w", kind=AutomationNodeKind.ACTION, type="widget.poke", params={})
    await _walk(
        [TRIGGER, node],
        [Edge("t", NodePort.OUT.value, "w")],
        Packet.of(FACTS, widget=widgets),
    )

    # Per item arity: once per widget, each seeing only its own id.
    assert plugin_action["planned"] == [(widgets[0],), (widgets[1],)]
    assert plugin_action["applied"] == [(widgets[0],), (widgets[1],)]


async def test_a_dry_run_plans_a_contributed_action_but_never_applies_it(plugin_action):
    """The plan/apply split is what makes the dry run free AND identical."""
    report = await _walk(
        [TRIGGER, Node(id="w", kind=AutomationNodeKind.ACTION, type="widget.poke", params={})],
        [Edge("t", NodePort.OUT.value, "w")],
        Packet.of(FACTS, widget=[uuid.uuid4()]),
        apply=False,
    )

    assert plugin_action["planned"], "planning still happens"
    assert plugin_action["applied"] == [], "applying does not"
    assert report.plans and report.plans[0].action_type == "widget.poke"


async def test_a_contributed_action_is_metered_by_the_run_budget(plugin_action, monkeypatch):
    """It shares the executor's budget rather than having its own — a plugin
    cannot buy itself more fan-out than the engine allows."""
    monkeypatch.setattr(executor.settings, "automation_graph_max_item_actions", 2)
    report = await _walk(
        [TRIGGER, Node(id="w", kind=AutomationNodeKind.ACTION, type="widget.poke", params={})],
        [Edge("t", NodePort.OUT.value, "w")],
        Packet.of(FACTS, widget=[uuid.uuid4() for _ in range(5)]),
    )

    assert len(plugin_action["applied"]) == 2
    assert report.dropped and "3 of 5" in report.dropped[0]


async def test_whatever_a_contributed_action_emits_is_marked_automation_caused(monkeypatch):
    """THE containment property. A plugin action that emits an event which its own
    automation subscribes to would spin forever — unless the emit is marked, and
    the marking is the executor's job, not the plugin's. `apply` runs inside
    `events.automated()`, so the plugin gets loop safety by doing nothing."""
    from radd.modules.events import service as events

    seen: dict[str, bool] = {}

    async def plan(_ctx):
        seen["planning"] = events.is_automated()
        return type("P", (), {"detail": "d", "resolves": True})()

    async def apply(_ctx, _plan):
        seen["applying"] = events.is_automated()

    monkeypatch.setitem(
        registries.entity_refs, "widget", EntityRefSpec("widget", lambda *_: None)
    )
    monkeypatch.setitem(
        registries.automation_nodes,
        "widget.emit",
        AutomationNodeSpec(
            key="widget.emit", kind="action", label="Emit",
            subject="widget", arity="item", needs_items=False, plan=plan, apply=apply,
        ),
    )
    await _walk(
        [TRIGGER, Node(id="w", kind=AutomationNodeKind.ACTION, type="widget.emit", params={})],
        [Edge("t", NodePort.OUT.value, "w")],
        Packet.of(FACTS, widget=[uuid.uuid4()]),
    )

    assert seen["applying"] is True, "an emit during apply must be automation-caused"
    # Planning writes nothing, so it is deliberately outside the scope — a dry
    # run must not look like an automation-caused mutation.
    assert seen["planning"] is False


async def test_a_raising_contributed_action_does_not_take_the_branch_down(monkeypatch):
    """One bad plugin must not stop a graph that has other work to do — the same
    best-effort property every built-in action has."""
    monkeypatch.setitem(
        registries.entity_refs, "widget", EntityRefSpec("widget", lambda *_: None)
    )

    async def boom(_ctx):
        raise RuntimeError("the plugin is having a day")

    monkeypatch.setitem(
        registries.automation_nodes,
        "widget.boom",
        AutomationNodeSpec(
            key="widget.boom", kind="action", label="Boom",
            subject="widget", arity="item", needs_items=False, plan=boom,
        ),
    )
    node = Node(id="w", kind=AutomationNodeKind.ACTION, type="widget.boom", params={})
    report = await _walk(
        [TRIGGER, node], [Edge("t", NodePort.OUT.value, "w")], Packet.of(FACTS, widget=[uuid.uuid4()])
    )

    assert report.per_node["w"]["in"] == 0  # the walk completed rather than raising


async def test_the_milestones_plugin_contributes_a_real_action():
    """The acceptance test for "organic but consistent": a plugin's own event, a
    kernel-written ref, and the plugin's own action — with no edits to
    `automations`, the kernel, or the SPA."""
    spec = registries.automation_nodes["milestone.set_status"]
    assert spec.kind == "action"
    assert spec.subject == "milestone"
    assert spec.permission == "milestone.update"
    assert spec.plan is not None and spec.apply is not None
    # And its action is not, and never will be, in the built-in enum.
    from radd.modules.automations.types import ActionType

    assert "milestone.set_status" not in {a.value for a in ActionType}
