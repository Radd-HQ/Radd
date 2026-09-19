"""The scripts plugin (RADD-1269): the child contract, the two nodes, the
script library, the package vocabulary — with this process's own interpreter
standing in for the managed venv, so nothing here needs uv."""

import sys
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.kernel import registries
from radd.modules.auth.models import ApiToken, User
from radd.modules.automations import service as automations
from radd.modules.automations.schemas import RuleCreate
from radd.modules.scripts import nodes, runner, service
from radd.modules.scripts.schemas import PackageCreate, ScriptCreate, ScriptUpdate
from radd.modules.scripts.types import NODE_DECIDE, NODE_RUN, UNAVAILABLE_PORT

PY = sys.executable


@pytest.fixture
async def db():
    engine_ = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine_.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(email=f"scr-{uuid.uuid4().hex[:8]}@example.com", name="Script Admin", instance_role="admin")
    db.add(user)
    await db.flush()
    return user


# --- the child contract ------------------------------------------------------


async def test_a_script_returns_a_dict_and_logs_to_stderr():
    outcome = await runner.run(
        "def main(ctx):\n    ctx.log('hello')\n    return {'count': len(ctx.items), 'first': ctx.item['key']}\n",
        {"items": [{"key": "TD-1"}], "vars": {}, "params": {}},
        timeout=20,
        python=PY,
    )
    assert outcome.ok, outcome
    assert outcome.result == {"count": 1, "first": "TD-1"}
    assert "hello" in outcome.stderr
    assert outcome.duration_ms >= 0


async def test_a_script_that_raises_reports_the_last_traceback_line():
    outcome = await runner.run("def main(ctx):\n    raise ValueError('boom')\n", {}, timeout=20, python=PY)
    assert not outcome.ok
    assert "ValueError: boom" in outcome.error
    assert "Traceback" in outcome.stderr


async def test_a_script_without_main_is_an_error():
    outcome = await runner.run("x = 1\n", {}, timeout=20, python=PY)
    assert not outcome.ok and "main" in outcome.error


async def test_a_script_that_hangs_is_killed_at_the_timeout():
    outcome = await runner.run("import time\ndef main(ctx):\n    time.sleep(30)\n", {}, timeout=1, python=PY)
    assert not outcome.ok and "timed out" in outcome.error


async def test_the_child_does_not_inherit_the_server_environment(monkeypatch):
    monkeypatch.setenv("RADD_DATABASE_URL", "postgresql://secret")
    outcome = await runner.run(
        "import os\ndef main(ctx):\n    return {'db': os.environ.get('RADD_DATABASE_URL'), 'url': os.environ.get('RADD_URL')}\n",
        {"radd_url": "http://radd.test"},
        timeout=20,
        python=PY,
    )
    assert outcome.ok and outcome.result == {"db": None, "url": "http://radd.test"}


async def test_the_client_is_lazy_and_refuses_without_a_key():
    outcome = await runner.run(
        "def main(ctx):\n    try:\n        ctx.client\n    except RuntimeError as e:\n        return str(e)\n",
        {},
        timeout=20,
        python=PY,
    )
    assert outcome.ok and "no Radd API" in outcome.result


# --- the library --------------------------------------------------------------


async def test_scripts_are_versioned_and_named_uniquely(db, admin):
    script = await service.create_script(db, ScriptCreate(name="Greeter", body="def main(ctx):\n    return 1\n"), admin.id)
    assert script.version == 1
    await service.update_script(db, script.id, ScriptUpdate(body="def main(ctx):\n    return 2\n", note="two"), admin.id)
    assert script.version == 2
    await service.update_script(db, script.id, ScriptUpdate(description="just a note"), admin.id)
    assert script.version == 2, "a description edit is not a new version of the code"
    versions = await service.list_versions(db, script.id)
    assert [v.version for v in versions] == [2, 1] and versions[0].note == "two"
    from radd.exceptions import ConflictError

    with pytest.raises(ConflictError):
        await service.create_script(db, ScriptCreate(name="Greeter", body=""), admin.id)


def test_package_specs_are_names_with_versions_never_urls_or_options():
    for good in ("requests", "requests>=2.31", "pandas==2.2.*", "google-api-python-client", "x[extra]>=1,<2"):
        PackageCreate(spec=good)
    for bad in ("-e .", "git+https://x/y", "https://example.com/pkg.whl", "./local", "requests --pre", ""):
        with pytest.raises(ValidationError):
            PackageCreate(spec=bad)
    assert service.package_name("Google_API.Client>=1") == "google-api-client"


# --- the nodes ----------------------------------------------------------------


def test_the_nodes_are_registered_with_their_dynamic_shapes():
    run = registries.automation_nodes[NODE_RUN]
    decide = registries.automation_nodes[NODE_DECIDE]
    assert run.kind == "action" and decide.kind == "gate"
    assert [o.name for o in run.outputs_at({"outputs": ["total", "bad name", "ok_1"]})] == ["total", "ok_1"]
    assert decide.ports_at({"ports": ["yes", "no"]}) == ("yes", "no", UNAVAILABLE_PORT)
    with pytest.raises(ValueError):
        nodes.check_decide({"ports": []})
    with pytest.raises(ValueError):
        nodes.check_run({"outputs": ["not a token"]})


class _Node:
    def __init__(self, params):
        self.id = "s1"
        self.params = params


class _Facts:
    event_type = "item.updated"
    actor_id = actor_email = actor_name = None
    payload = {}


class _Packet:
    def __init__(self):
        self.facts = _Facts()
        self.vars = {"triage": {"priority": "high"}}


class _Ctx:
    def __init__(self, session, actor, params, ids=()):
        self.session, self.actor, self.node = session, actor, _Node(params)
        self.subject_ids = tuple(ids)
        self.packet = _Packet()
        self.outputs = {}

    def set_output(self, name, value):
        self.outputs[name] = "" if value is None else str(value)


async def test_run_node_plans_by_name_and_publishes_the_returned_dict(db, admin, monkeypatch):
    monkeypatch.setattr(settings, "scripts_max_timeout_seconds", 20)
    await service.create_script(
        db,
        ScriptCreate(name="Totals", body="def main(ctx):\n    return {'total': len(ctx.items), 'who': ctx.vars['triage']['priority']}\n"),
        admin.id,
    )
    # Substitute this interpreter for the managed one, and keep the mint/discard
    # on the test session (it commits — the real thing must, see run_body).
    original = service.run_body

    async def run_here(session, body, payload, **kw):
        return await runner.run(body, payload, timeout=kw["timeout"], python=PY)

    monkeypatch.setattr(service, "run_body", run_here)
    ctx = _Ctx(db, admin, {"script": "Totals", "outputs": ["total", "who"], "timeout": 10})
    plan = await nodes.plan_run(ctx)
    assert plan.resolves and "Totals" in plan.detail
    await nodes.apply_run(ctx, plan)
    assert ctx.outputs == {"total": "0", "who": "high"}

    missing = await nodes.plan_run(_Ctx(db, admin, {"script": "Nope"}))
    assert not missing.resolves and "no script named" in missing.detail
    monkeypatch.setattr(service, "run_body", original)


async def test_run_node_raises_on_failure_so_the_report_says_so(db, admin, monkeypatch):
    await service.create_script(db, ScriptCreate(name="Broken", body="def main(ctx):\n    raise RuntimeError('nope')\n"), admin.id)

    async def run_here(session, body, payload, **kw):
        return await runner.run(body, payload, timeout=kw["timeout"], python=PY)

    monkeypatch.setattr(service, "run_body", run_here)
    ctx = _Ctx(db, admin, {"script": "Broken"})
    with pytest.raises(RuntimeError, match="nope"):
        await nodes.apply_run(ctx, await nodes.plan_run(ctx))


async def test_decide_node_takes_the_named_port_or_unavailable(db, admin, monkeypatch):
    await service.create_script(db, ScriptCreate(name="Router", body="def main(ctx):\n    return ctx.params['want']\n"), admin.id)

    async def run_here(session, body, payload, **kw):
        return await runner.run(body, payload, timeout=kw["timeout"], python=PY)

    monkeypatch.setattr(service, "run_body", run_here)
    assert await nodes.plan_decide(_Ctx(db, admin, {"script": "Router", "ports": ["yes", "no"], "want": "yes"})) == "yes"
    assert await nodes.plan_decide(_Ctx(db, admin, {"script": "Router", "ports": ["yes", "no"], "want": "maybe"})) == UNAVAILABLE_PORT
    assert await nodes.plan_decide(_Ctx(db, admin, {"script": "Gone", "ports": ["yes"]})) == UNAVAILABLE_PORT


async def test_the_run_key_is_minted_for_the_actor_and_discarded(db, admin, monkeypatch):
    """The real `run_body`: the child sees a key, and the row is gone after."""
    seen = {}

    async def fake_run(body, payload, *, timeout, python=None):
        seen["token"] = payload.get("radd_token")
        seen["url"] = payload.get("radd_url")
        rows = (await db.execute(select(ApiToken).where(ApiToken.user_id == admin.id))).scalars().all()
        seen["rows_during"] = len(rows)
        return runner.Outcome(True, result={})

    monkeypatch.setattr(runner, "run", fake_run)
    outcome = await service.run_body(db, "def main(ctx): return {}", {}, actor=admin, timeout=5, label="t")
    assert outcome.ok
    assert seen["token"].startswith("radd_pat_") and seen["url"] == settings.app_base_url
    assert seen["rows_during"] == 1
    rows = (await db.execute(select(ApiToken).where(ApiToken.user_id == admin.id))).scalars().all()
    assert rows == []
    # This test committed (run_body must); clean up the actor it made.
    await db.delete(admin)
    await db.commit()


async def test_a_script_node_saves_in_a_graph_and_the_catalog_lists_it(db, admin):
    await service.create_script(db, ScriptCreate(name="Saver", body="def main(ctx):\n    return {}\n"), admin.id)
    rule = await automations.create_rule(
        db,
        RuleCreate.model_validate(
            {
                "name": "scripted",
                "nodes": [
                    {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.updated"}},
                    {"id": "gate", "kind": "gate", "type": NODE_DECIDE, "params": {"script": "Saver", "ports": ["go"]}},
                    {"id": "act", "kind": "action", "type": NODE_RUN, "name": "totals",
                     "params": {"script": "Saver", "outputs": ["total"]}},
                    {"id": "say", "kind": "action", "type": "action.add_comment",
                     "params": {"body": "{{totals.total}}", "visibility": "public"}},
                ],
                "edges": [
                    {"source": "trg", "port": "out", "target": "gate"},
                    {"source": "gate", "port": "go", "target": "act"},
                    {"source": "act", "port": "out", "target": "say"},
                ],
            }
        ),
        admin.id,
    )
    assert rule.id
