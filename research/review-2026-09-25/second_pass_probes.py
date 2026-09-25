"""Second-pass review probes: passing means the reported behavior was reproduced.

Run with PYTHONPATH=server/tests and the normal conftest plugin. Only the isolated
test database is used. Script processes, mail and real providers are not invoked.
"""
import importlib
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from test_review_interactions import world  # noqa: F401
from radd.modules.auth.models import User, ApiToken
from radd.modules.automations import engine, service as automations
from radd.modules.automations.schemas import RuleCreate
from radd.modules.automations.models import AutomationRun
from radd.modules.items import service as items
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.vcs import service as vcs, receiving
from radd.modules.vcs.types import VcsProvider, VcsRefType


async def rule(db, admin, nodes, edges):
    return await automations.create_rule(db, RuleCreate(name=f"Probe {uuid.uuid4().hex}", nodes=nodes, edges=edges), admin.id)


def trigger(event="manual"):
    return {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": event}}


def wire(source, target, port="out"):
    return {"source": source, "port": port, "target": target}


async def test_script_gate_preview_commits_pending_rows_and_gets_write_capable_key(world, monkeypatch):
    from radd.modules.scripts import runner
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Pending preview draft"), admin)
    calls = []
    async def run(body, payload, **kwargs):
        calls.append(payload)
        token = await db.scalar(select(ApiToken).where(ApiToken.user_id == admin.id))
        assert token is not None and token.scopes is None
        return runner.Outcome(True, result="yes")
    monkeypatch.setattr(runner, "run", run)
    automation = await rule(db, admin, [trigger(), {"id": "s", "kind": "gate", "type": "script.decide", "params": {"body": "def main(ctx): return 'yes'", "ports": ["yes", "no"]}}], [wire("t", "s")])
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as observer:
        assert await observer.get(WorkItem, item.id) is None
    await engine.preview(db, automation, item.id)
    assert calls and calls[0]["radd_token"]
    async with maker() as observer:
        assert await observer.get(WorkItem, item.id) is not None


async def test_script_gate_in_rejecting_validation_leaves_created_item(world, monkeypatch):
    from radd.modules.scripts import runner
    from radd.modules.automations import intake
    db, admin, project = world
    async def run(*args, **kwargs): return runner.Outcome(True, result="yes")
    monkeypatch.setattr(runner, "run", run)
    start = trigger("validate")
    start["params"]["targets"] = [{"kind": "project", "id": str(project.id)}]
    await rule(db, admin, [start,
        {"id": "s", "kind": "gate", "type": "script.decide", "params": {"body": "def main(ctx): return 'yes'", "ports": ["yes"]}},
        {"id": "b", "kind": "action", "type": "verdict.block", "params": {"message": "Rejected"}},
    ], [wire("t", "s"), wire("s", "b", "yes")])
    title = f"Rejected but committed {uuid.uuid4().hex}"
    with pytest.raises(Exception) as failure:
        await intake.validate_and_create(db, ItemCreate(project_id=project.id, title=title), admin)
    assert "closed" in str(failure.value).lower(), repr(failure.value)
    async with async_sessionmaker(db.bind, expire_on_commit=False)() as observer:
        assert await observer.scalar(select(WorkItem).where(WorkItem.title == title)) is not None


async def test_disabling_act_as_user_elevates_node_to_author(world):
    db, admin, project = world
    limited = User(email=f"limited-{uuid.uuid4().hex}@example.test", name="Limited", instance_role="member")
    db.add(limited)
    await db.flush()
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Identity probe"), admin)
    automation = await rule(db, admin, [trigger(), {"id": "a", "kind": "action", "type": "action.set_flag", "params": {"flagged": True, "act_as": limited.email}}], [wire("t", "a")])
    await engine.run_manual(db, automation, item.id, start_node_id="t")
    target = await items.require_item(db, item.id)
    assert not target.flagged
    limited.active = False
    await db.flush()
    await engine.run_manual(db, automation, item.id, start_node_id="t")
    assert target.flagged


async def test_action_failure_continues_success_path_and_reports_applied(world, monkeypatch):
    from radd.modules.automations import builtin_actions
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Failure probe"), admin)
    automation = await rule(db, admin, [trigger(),
        {"id": "bad", "kind": "action", "type": "action.set_priority", "params": {"priority": "high"}},
        {"id": "next", "kind": "action", "type": "action.set_flag", "params": {"flagged": True}},
    ], [wire("t", "bad"), wire("bad", "next")])
    original = builtin_actions.apply_action
    async def broken(ctx, plan):
        if ctx.node.id == "bad": raise RuntimeError("provider unavailable")
        return await original(ctx, plan)
    monkeypatch.setattr(builtin_actions, "apply_action", broken)
    assert await engine.run_manual(db, automation, item.id, start_node_id="t")
    run = await db.scalar(select(AutomationRun).where(AutomationRun.automation_id == automation.id))
    assert run.status == "applied" and run.error == ""
    assert "failed" in run.report["would_apply"][0]["detail"]
    assert (await items.require_item(db, item.id)).flagged


async def test_configured_vcs_merge_template_cannot_be_previewed(world):
    github_router = importlib.import_module("radd.modules.github.router")
    from radd.modules.automations.graph import Packet
    from radd.modules.automations.conditions import EventFacts
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Preview merge"), admin)
    template = github_router.TRIGGERS.templates()[0]
    nodes = [dict(n, params=dict(n["params"])) for n in template.nodes]
    nodes[1]["params"]["value"] = "team/repo"
    automation = await rule(db, admin, nodes, list(template.edges))
    preview = await engine.preview(db, automation, item.id)
    assert not preview.would_apply
    actual = await engine.run_graph(db, automation, Packet.of(EventFacts(event_type="github.pull_request.merged", actor_id=str(admin.id), actor_email=admin.email, actor_name=admin.name, payload={"repo": "team/repo"}), item=(item.id,)), admin, apply=False)
    assert any(plan.resolves for plan in actual.plans)


async def test_same_repository_name_on_two_connections_routes_only_first(world):
    from radd.modules.gitlab import service
    from radd.modules.gitlab.schemas import ConnectionCreate, RepoCreate
    db, admin, project = world
    connections = [await service.create_connection(db, ConnectionCreate(name=f"Host {uuid.uuid4().hex}", base_url=f"https://host{i}.example.test", webhook_secret=f"secret{i}")) for i in range(2)]
    name = f"team/{uuid.uuid4().hex}"
    for connection in connections:
        await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name=name, project_id=project.id))
    results = [await service.resolve_for_payload(db, {"project": {"path_with_namespace": name}}, f"secret{i}") for i in range(2)]
    assert sum(result is not None for result in results) == 1


async def test_ref_identity_overwrites_other_host_url(world):
    from radd.modules.vcs.ids import pr_external_id
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Host collision"), admin)
    rows = [await vcs.upsert_vcs_link(db, item.id, provider=VcsProvider.FORGEJO, ref_type=VcsRefType.PULL_REQUEST,
        external_id=pr_external_id("team/repo", 7), title=f"Host {i}", url=f"https://host{i}.test/team/repo/pulls/7") for i in range(2)]
    assert rows[0].id == rows[1].id and rows[0].url.startswith("https://host1.")


async def test_pr_mention_removed_leaves_open_link_even_after_merge(world):
    from radd.modules.github import parsing
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Unmentioned"), admin)
    key = f"{project.key}-{item.number}"
    payload = {"action": "opened", "repository": {"full_name": "team/repo"}, "pull_request": {"number": 7, "title": f"Fix {key}", "head": {"ref": "feature"}, "state": "open", "html_url": "https://git.test/pr/7"}}
    await receiving.link_planned(db, parsing.plan_pull_request(payload), provider=VcsProvider.GITHUB, actor_id=admin.id)
    payload["pull_request"].update(title="Fix something", state="closed", merged=True)
    payload["action"] = "closed"
    assert not await receiving.link_planned(db, parsing.plan_pull_request(payload), provider=VcsProvider.GITHUB, actor_id=admin.id)
    links = await vcs.list_for_item(db, item.id)
    assert len(links) == 1 and links[0].status == "open"


async def test_github_ci_red_turns_green_after_other_check_and_repeats_event(world):
    github_router = importlib.import_module("radd.modules.github.router")
    from radd.modules.github.types import GithubEventKind
    from radd.modules.vcs.ids import branch_external_id
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="CI aggregation"), admin)
    link = await vcs.upsert_vcs_link(db, item.id, provider=VcsProvider.GITHUB, ref_type=VcsRefType.BRANCH,
        external_id=branch_external_id("team/repo", "main"), title="main", url="https://git.test/tree/main")
    def payload(name, result, run_id):
        return {"repository": {"full_name": "team/repo"}, "check_run": {"id": run_id, "name": name, "conclusion": result, "head_sha": "abc", "check_suite": {"head_branch": "main"}}}
    assert (await github_router._handle_ci(db, GithubEventKind.CHECK_RUN, payload("tests", "failure", 100)))["triggered"] == 1
    assert link.ci_state == "failure"
    green = payload("formatting", "success", 101)
    assert (await github_router._handle_ci(db, GithubEventKind.CHECK_RUN, green))["triggered"] == 1
    assert link.ci_state == "success"
    # A distinct webhook type/body bypasses delivery-ID deduplication normally.
    workflow = {"repository": {"full_name": "team/repo"}, "workflow_run": {
        "id": 100, "head_branch": "main", "head_sha": "abc", "conclusion": "success"}}
    assert (await github_router._handle_ci(db, GithubEventKind.WORKFLOW_RUN, workflow))["triggered"] == 1
    workflow["workflow_run"].update(id=1, conclusion=None, status="in_progress")
    await github_router._handle_ci(db, GithubEventKind.WORKFLOW_RUN, workflow)
    assert link.ci_state == "running"


async def test_deleted_vcs_env_seed_returns(world, monkeypatch):
    from contextlib import asynccontextmanager
    from radd.config import settings
    from radd.modules.forgejo import service
    from radd.modules.forgejo.models import ForgejoConnection
    from sqlalchemy import delete
    db, admin, project = world
    await db.execute(delete(ForgejoConnection))
    @asynccontextmanager
    async def factory(): yield db
    async def commit(): await db.flush()
    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(db, "commit", commit)
    monkeypatch.setattr(settings, "forgejo_webhook_secret", "review-seed")
    await service.seed_from_env()
    first = await db.scalar(select(ForgejoConnection))
    await service.delete_connection(db, first.id)
    await service.seed_from_env()
    second = await db.scalar(select(ForgejoConnection))
    assert second is not None and second.id != first.id and second.active


async def test_state_gate_runs_false_branch_webhook_even_when_subject_matches(world):
    from radd.modules.workflow.models import State
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Gate semantics"), admin)
    target = await items.require_item(db, item.id)
    category = (await db.get(State, target.state_id)).category
    automation = await rule(db, admin, [trigger(),
        {"id": "g", "kind": "gate", "type": "gate.state_category", "params": {"categories": [category]}},
        {"id": "w", "kind": "action", "type": "action.send_webhook", "params": {"url": "https://example.test/false-branch"}},
    ], [wire("t", "g"), wire("g", "w", "false")])
    result = await engine.preview(db, automation, item.id)
    assert len(result.would_apply) == 1 and result.would_apply[0].resolves


async def test_preview_does_not_predict_created_branch(world):
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Original"), admin)
    automation = await rule(db, admin, [trigger(),
        {"id": "c", "kind": "action", "type": "action.create_item", "params": {"project": project.key, "title": "Followup"}},
        {"id": "f", "kind": "action", "type": "action.set_flag", "params": {"flagged": True}},
    ], [wire("t", "c"), wire("c", "f", "created")])
    preview = await engine.preview(db, automation, item.id)
    assert [p.node_id for p in preview.would_apply] == ["c"]
    await engine.run_manual(db, automation, item.id, start_node_id="t")
    created = await db.scalar(select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.title == "Followup"))
    assert created is not None and created.flagged


async def test_repo_mapping_is_not_scope_and_deleting_repo_does_not_stop_ingestion(world):
    from radd.modules.gitlab import service, parsing
    from radd.modules.gitlab.schemas import ConnectionCreate, RepoCreate
    from radd.modules.projects import service as projects
    from radd.modules.projects.schemas import ProjectCreate
    db, admin, project = world
    other = await projects.create_project(db, ProjectCreate(key=f"OT{uuid.uuid4().hex[:5].upper()}", name="Other project"))
    item = await items.create_item(db, ItemCreate(project_id=other.id, title="Outside mapped project"), admin)
    connection = await service.create_connection(db, ConnectionCreate(name=uuid.uuid4().hex, base_url="https://git.test", webhook_secret="review-scope"))
    name = f"team/{uuid.uuid4().hex}"
    repo = await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name=name, project_id=project.id))
    payload = {"project": {"path_with_namespace": name, "web_url": f"https://git.test/{name}"}, "ref": "refs/heads/main", "commits": [{"id": "abc", "message": f"Fix {other.key}-{item.number}", "url": "https://git.test/commit/abc"}]}
    assert await service.resolve_for_payload(db, payload, "review-scope") is not None
    links = await receiving.link_planned(db, parsing.plan_push(payload), provider=VcsProvider.GITLAB, actor_id=admin.id)
    assert item.id in links
    await service.delete_repo(db, repo.id)
    resolved = await service.resolve_for_payload(db, payload, "review-scope")
    assert resolved is not None and resolved[0].id == connection.id and resolved[1] is None
