"""The scripts plugin (RADD-1269, reshaped by RADD-1272): the child contract, the
two nodes with the body on the node, the package vocabulary — with this process's own interpreter
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
from radd.modules.scripts import interpreter, nodes, runner, service
from radd.modules.scripts.schemas import InterpreterSettings, PackageCreate, RunRequest
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


def test_package_specs_are_names_with_versions_never_urls_or_options():
    for good in ("requests", "requests>=2.31", "pandas==2.2.*", "google-api-python-client", "x[extra]>=1,<2"):
        PackageCreate(spec=good)
    for bad in ("-e .", "git+https://x/y", "https://example.com/pkg.whl", "./local", "requests --pre", ""):
        with pytest.raises(ValidationError):
            PackageCreate(spec=bad)
    assert service.package_name("Google_API.Client>=1") == "google-api-client"


# --- where packages come from (RADD-1277) -------------------------------------


async def test_the_build_is_offline_when_the_sdk_is_a_bundled_wheel(tmp_path, monkeypatch):
    """The air-gap contract: with the SDK wheel in a wheelhouse, no uv call of
    the rebuild may reach an index — no `--seed`, `--offline` on the install,
    every wheelhouse on the command line. A package install then follows the
    row: the admin's index, offline only when asked."""
    house = tmp_path / "image-wheels"
    house.mkdir()
    (house / "radd_sdk-0.1.0-py3-none-any.whl").write_bytes(b"")
    (tmp_path / "scripts" / "wheels").mkdir(parents=True)
    monkeypatch.setattr(settings, "scripts_dir", str(tmp_path / "scripts"))
    monkeypatch.setattr(settings, "scripts_find_links", str(house))
    monkeypatch.setattr(settings, "scripts_sdk_source", "")
    calls: list[tuple[str, ...]] = []

    async def record(*args, timeout=None):
        calls.append(args)
        if args[1:2] == ("venv",):
            (tmp_path / "scripts" / "venv" / "bin").mkdir(parents=True)
            (tmp_path / "scripts" / "venv" / "bin" / "python").write_text("")
        return interpreter.ToolResult(True, "3.12.0", 0)

    monkeypatch.setattr(interpreter, "_run", record)
    assert interpreter.sdk_is_bundled()
    result = await interpreter.rebuild("3.12")
    assert result.ok
    venv, sdk = calls[0], calls[1]
    assert "--seed" not in venv
    assert "--offline" in sdk and sdk[-1].endswith("radd_sdk-0.1.0-py3-none-any.whl")
    assert sdk.count("--find-links") == 2 and str(house) in sdk and str(tmp_path / "scripts" / "wheels") in sdk
    assert "--index-url" not in sdk

    calls.clear()
    await interpreter.install("requests", index_url="https://pypi.example.com/simple", offline=False)
    (package,) = calls
    assert "--offline" not in package
    assert package[package.index("--index-url") + 1] == "https://pypi.example.com/simple"


def test_the_index_url_is_a_simple_index_and_its_password_is_masked():
    for good in ("", "https://pypi.example.com/simple", "http://user:s3cret@mirror.local:8080/simple/"):
        InterpreterSettings(index_url=good)
    for bad in ("pypi.example.com", "ftp://x/y", "https://x y/simple"):
        with pytest.raises(ValidationError):
            InterpreterSettings(index_url=bad)
    assert interpreter.masked_url("http://user:s3cret@mirror.local:8080/simple/") == "http://user:***@mirror.local:8080/simple/"
    assert interpreter.masked_url("https://pypi.example.com/simple") == "https://pypi.example.com/simple"


# --- the nodes ----------------------------------------------------------------


def test_the_nodes_are_registered_with_their_dynamic_shapes():
    run = registries.automation_nodes[NODE_RUN]
    decide = registries.automation_nodes[NODE_DECIDE]
    assert run.kind == "action" and decide.kind == "gate"
    assert [o.name for o in run.outputs_at({"outputs": ["total", "bad name", "ok_1"]})] == ["total", "ok_1"]
    assert decide.ports_at({"ports": ["yes", "no"]}) == ("yes", "no", UNAVAILABLE_PORT)
    with pytest.raises(ValueError):
        nodes.check_decide({"body": "def main(ctx): pass", "ports": []})
    with pytest.raises(ValueError):
        nodes.check_run({"body": "def main(ctx): pass", "outputs": ["not a token"]})
    with pytest.raises(ValueError, match="main"):
        nodes.check_run({"body": "x = 1", "outputs": []})


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


TOTALS = "def main(ctx):\n    return {'total': len(ctx.items), 'who': ctx.vars['triage']['priority']}\n"


async def test_run_node_runs_the_body_on_the_node_and_publishes_the_returned_dict(db, admin, monkeypatch):
    monkeypatch.setattr(settings, "scripts_max_timeout_seconds", 20)
    # Substitute this interpreter for the managed one.
    async def run_here(session, body, payload, **kw):
        return await runner.run(body, payload, timeout=kw["timeout"], python=PY)

    monkeypatch.setattr(service, "run_body", run_here)
    ctx = _Ctx(db, admin, {"body": TOTALS, "outputs": ["total", "who"], "timeout": 10})
    plan = await nodes.plan_run(ctx)
    assert plan.resolves
    await nodes.apply_run(ctx, plan)
    assert ctx.outputs == {"total": "0", "who": "high"}

    empty = await nodes.plan_run(_Ctx(db, admin, {"body": "   "}))
    assert not empty.resolves and "no script" in empty.detail
    no_main = await nodes.plan_run(_Ctx(db, admin, {"body": "x = 1"}))
    assert not no_main.resolves and "main" in no_main.detail


async def test_run_node_raises_on_failure_so_the_report_says_so(db, admin, monkeypatch):
    async def run_here(session, body, payload, **kw):
        return await runner.run(body, payload, timeout=kw["timeout"], python=PY)

    monkeypatch.setattr(service, "run_body", run_here)
    ctx = _Ctx(db, admin, {"body": "def main(ctx):\n    raise RuntimeError('nope')\n"})
    with pytest.raises(RuntimeError, match="nope"):
        await nodes.apply_run(ctx, await nodes.plan_run(ctx))


ROUTER = "def main(ctx):\n    return ctx.params['want']\n"


async def test_decide_node_takes_the_named_port_or_unavailable(db, admin, monkeypatch):
    async def run_here(session, body, payload, **kw):
        return await runner.run(body, payload, timeout=kw["timeout"], python=PY)

    monkeypatch.setattr(service, "run_body", run_here)
    assert await nodes.plan_decide(_Ctx(db, admin, {"body": ROUTER, "ports": ["yes", "no"], "want": "yes"})) == "yes"
    assert await nodes.plan_decide(_Ctx(db, admin, {"body": ROUTER, "ports": ["yes", "no"], "want": "maybe"})) == UNAVAILABLE_PORT
    assert await nodes.plan_decide(_Ctx(db, admin, {"body": "", "ports": ["yes"]})) == UNAVAILABLE_PORT


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


async def test_the_test_box_seeds_one_item_by_key(db, admin, monkeypatch):
    from radd.modules.items import service as items_service
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate

    project = await projects_service.create_project(db, ProjectCreate(key=f"ST{uuid.uuid4().hex[:4].upper()}", name="T"))
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="seeded"), admin)

    async def run_here(session, body, payload, **kw):
        return await runner.run(body, payload, timeout=kw["timeout"], python=PY)

    monkeypatch.setattr(service, "run_body", run_here)
    outcome = await service.run_test(
        db, RunRequest(body="def main(ctx):\n    return ctx.item['title']\n", item_key=item.key.lower(), timeout=10), admin
    )
    assert outcome.ok and outcome.result == "seeded"


async def test_a_script_node_saves_in_a_graph_and_the_catalog_lists_it(db, admin):
    rule = await automations.create_rule(
        db,
        RuleCreate.model_validate(
            {
                "name": "scripted",
                "nodes": [
                    {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.updated"}},
                    {"id": "gate", "kind": "gate", "type": NODE_DECIDE, "params": {"body": ROUTER, "ports": ["go"]}},
                    {"id": "act", "kind": "action", "type": NODE_RUN, "name": "totals",
                     "params": {"body": TOTALS, "outputs": ["total"]}},
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
