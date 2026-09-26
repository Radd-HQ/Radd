"""Regression coverage for the second automation and VCS review."""

import importlib
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from test_review_interactions import world as review_world

from radd.modules.auth.models import User, ApiToken
from radd.modules.automations import engine, service as automations
from radd.modules.automations.schemas import RuleCreate
from radd.modules.automations.models import AutomationRun
from radd.modules.items import service as items
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.vcs import service as vcs, receiving
from radd.modules.vcs.types import VcsProvider, VcsRefType


world = review_world


async def rule(db, admin, nodes, edges):
    return await automations.create_rule(
        db, RuleCreate(name=f"Probe {uuid.uuid4().hex}", nodes=nodes, edges=edges), admin.id
    )


def trigger(event="manual"):
    return {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": event}}


def wire(source, target, port="out"):
    return {"source": source, "port": port, "target": target}


async def test_script_gate_preview_never_executes_or_commits_pending_rows(world, monkeypatch):
    from radd.modules.scripts import runner

    db, admin, project = world
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Pending preview draft"), admin
    )
    calls = []

    async def run(body, payload, **kwargs):
        calls.append(payload)
        token = await db.scalar(select(ApiToken).where(ApiToken.user_id == admin.id))
        assert token is not None and token.scopes is None
        return runner.Outcome(True, result="yes")

    monkeypatch.setattr(runner, "run", run)
    automation = await rule(
        db,
        admin,
        [
            trigger(),
            {
                "id": "s",
                "kind": "gate",
                "type": "script.decide",
                "params": {"body": "def main(ctx): return 'yes'", "ports": ["yes", "no"]},
            },
        ],
        [wire("t", "s")],
    )
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as observer:
        assert await observer.get(WorkItem, item.id) is None
    preview = await engine.preview(db, automation, item.id)
    assert not calls
    assert any("script" in warning for warning in preview.dropped)
    async with maker() as observer:
        assert await observer.get(WorkItem, item.id) is None


async def test_script_gate_cannot_be_saved_in_submission_validation(world):
    from radd.exceptions import ConflictError

    db, admin, project = world
    start = trigger("validate")
    start["params"]["targets"] = [{"kind": "project", "id": str(project.id)}]
    with pytest.raises(ConflictError, match="script"):
        await rule(
            db,
            admin,
            [
                start,
                {
                    "id": "s",
                    "kind": "gate",
                    "type": "script.decide",
                    "params": {"body": "def main(ctx): return 'yes'", "ports": ["yes"]},
                },
                {
                    "id": "b",
                    "kind": "action",
                    "type": "verdict.block",
                    "params": {"message": "Rejected"},
                },
            ],
            [wire("t", "s"), wire("s", "b", "yes")],
        )


async def test_disabling_act_as_user_stops_execution_without_fallback(world):
    db, admin, project = world
    limited = User(
        email=f"limited-{uuid.uuid4().hex}@example.test", name="Limited", instance_role="member"
    )
    db.add(limited)
    await db.flush()
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Identity probe"), admin
    )
    automation = await rule(
        db,
        admin,
        [
            trigger(),
            {
                "id": "a",
                "kind": "action",
                "type": "action.set_flag",
                "params": {"flagged": True, "act_as": limited.email},
            },
        ],
        [wire("t", "a")],
    )
    await engine.run_manual(db, automation, item.id, start_node_id="t")
    target = await items.require_item(db, item.id)
    assert not target.flagged
    limited.active = False
    await db.flush()
    await engine.run_manual(db, automation, item.id, start_node_id="t")
    assert not target.flagged


async def test_action_failure_stops_success_path_and_reports_failure(world, monkeypatch):
    from radd.modules.automations import builtin_actions

    db, admin, project = world
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Failure probe"), admin
    )
    automation = await rule(
        db,
        admin,
        [
            trigger(),
            {
                "id": "bad",
                "kind": "action",
                "type": "action.set_priority",
                "params": {"priority": "high"},
            },
            {
                "id": "next",
                "kind": "action",
                "type": "action.set_flag",
                "params": {"flagged": True},
            },
        ],
        [wire("t", "bad"), wire("bad", "next")],
    )
    original = builtin_actions.apply_action

    async def broken(ctx, plan):
        if ctx.node.id == "bad":
            raise RuntimeError("provider unavailable")
        return await original(ctx, plan)

    monkeypatch.setattr(builtin_actions, "apply_action", broken)
    await engine.run_manual(db, automation, item.id, start_node_id="t")
    run = await db.scalar(select(AutomationRun).where(AutomationRun.automation_id == automation.id))
    assert run.status == "failed" and "provider unavailable" in run.error
    assert "failed" in run.report["would_apply"][0]["detail"]
    assert not (await items.require_item(db, item.id)).flagged


async def test_a_vcs_merge_automation_uses_sample_event_payload(world):
    """A merge rule gated on the repository previews against a sample payload.
    (It was the per-host template until RADD-1369 made that behaviour a
    repository switch; the graph is spelled out here instead.)"""
    github_router = importlib.import_module("radd.modules.github.router")
    from radd.modules.automations.graph import Packet
    from radd.modules.automations.conditions import EventFacts

    db, admin, project = world
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Preview merge"), admin
    )
    nodes = [
        {"id": "merge", "kind": "trigger", "type": "trigger.event", "params": {"event": str(github_router.TRIGGERS.merged)}},
        {"id": "repo", "kind": "gate", "type": "gate.payload", "params": {"path": "repo", "operator": "eq", "value": "team/repo"}},
        {"id": "move", "kind": "action", "type": "action.set_state", "params": {"state": "Done"}},
    ]
    edges = [
        {"source": "merge", "port": "out", "target": "repo"},
        {"source": "repo", "port": "true", "target": "move"},
    ]
    automation = await rule(db, admin, nodes, edges)
    preview = await engine.preview(db, automation, item.id, event_payload={"repo": "team/repo"})
    assert any(plan.resolves for plan in preview.would_apply)
    actual = await engine.run_graph(
        db,
        automation,
        Packet.of(
            EventFacts(
                event_type="github.pull_request.merged",
                actor_id=str(admin.id),
                actor_email=admin.email,
                actor_name=admin.name,
                payload={"repo": "team/repo"},
            ),
            item=(item.id,),
        ),
        admin,
        apply=False,
    )
    assert any(plan.resolves for plan in actual.plans)


async def test_same_repository_name_on_two_connections_authenticates_each_host(world):
    from radd.modules.gitlab import service
    from radd.modules.gitlab.schemas import ConnectionCreate, RepoCreate

    db, admin, project = world
    connections = [
        await service.create_connection(
            db,
            ConnectionCreate(
                name=f"Host {uuid.uuid4().hex}",
                base_url=f"https://host{i}.example.test",
                webhook_secret=f"secret{i}",
            ),
        )
        for i in range(2)
    ]
    name = f"team/{uuid.uuid4().hex}"
    for connection in connections:
        await service.create_repo(
            db, RepoCreate(connection_id=connection.id, full_name=name, project_id=project.id)
        )
    results = [
        await service.resolve_for_payload(
            db, {"project": {"path_with_namespace": name}}, f"secret{i}"
        )
        for i in range(2)
    ]
    assert [result[0].id for result in results] == [connection.id for connection in connections]


async def test_ref_identity_is_separate_for_each_host(world):
    from radd.modules.vcs.ids import pr_external_id

    db, admin, project = world
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Host collision"), admin
    )
    rows = [
        await vcs.upsert_vcs_link(
            db,
            item.id,
            provider=VcsProvider.FORGEJO,
            ref_type=VcsRefType.PULL_REQUEST,
            connection_id=uuid.uuid4(),
            external_id=pr_external_id("team/repo", 7),
            title=f"Host {i}",
            url=f"https://host{i}.test/team/repo/pulls/7",
        )
        for i in range(2)
    ]
    assert rows[0].id != rows[1].id and rows[0].url.startswith("https://host0.")


async def test_pr_mention_removed_keeps_historical_link_current(world):
    from radd.modules.github import parsing

    db, admin, project = world
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Unmentioned"), admin
    )
    key = f"{project.key}-{item.number}"
    payload = {
        "action": "opened",
        "repository": {"full_name": "team/repo"},
        "pull_request": {
            "number": 7,
            "title": f"Fix {key}",
            "head": {"ref": "feature"},
            "state": "open",
            "html_url": "https://git.test/pr/7",
        },
    }
    await receiving.link_planned(
        db, parsing.plan_pull_request(payload), provider=VcsProvider.GITHUB, actor_id=admin.id
    )
    payload["pull_request"].update(title="Fix something", state="closed", merged=True)
    payload["action"] = "closed"
    assert await receiving.link_planned(
        db, parsing.plan_pull_request(payload), provider=VcsProvider.GITHUB, actor_id=admin.id
    )
    links = await vcs.list_for_item(db, item.id)
    assert len(links) == 1 and links[0].status == "merged"


async def test_github_ci_aggregates_checks_and_ignores_repeats_and_older_runs(world):
    github_router = importlib.import_module("radd.modules.github.router")
    from radd.modules.github.types import GithubEventKind
    from radd.modules.vcs.ids import branch_external_id

    db, admin, project = world
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="CI aggregation"), admin
    )
    link = await vcs.upsert_vcs_link(
        db,
        item.id,
        provider=VcsProvider.GITHUB,
        ref_type=VcsRefType.BRANCH,
        external_id=branch_external_id("team/repo", "main"),
        title="main",
        url="https://git.test/tree/main",
    )

    def payload(name, result, run_id):
        return {
            "repository": {"full_name": "team/repo"},
            "check_run": {
                "id": run_id,
                "name": name,
                "conclusion": result,
                "head_sha": "abc",
                "check_suite": {"head_branch": "main"},
            },
        }

    assert (
        await github_router._handle_ci(
            db, GithubEventKind.CHECK_RUN, payload("tests", "failure", 100)
        )
    )["triggered"] == 0
    assert link.ci_state == "failure"
    green = payload("formatting", "success", 101)
    assert (await github_router._handle_ci(db, GithubEventKind.CHECK_RUN, green))["triggered"] == 0
    assert link.ci_state == "failure"
    # A distinct webhook type/body bypasses delivery-ID deduplication normally.
    workflow = {
        "repository": {"full_name": "team/repo"},
        "workflow_run": {
            "id": 100,
            "head_branch": "main",
            "head_sha": "abc",
            "conclusion": "success",
        },
    }
    assert (await github_router._handle_ci(db, GithubEventKind.WORKFLOW_RUN, workflow))[
        "triggered"
    ] == 1
    assert (await github_router._handle_ci(db, GithubEventKind.WORKFLOW_RUN, workflow))[
        "triggered"
    ] == 0
    workflow["workflow_run"].update(id=1, conclusion=None, status="in_progress")
    await github_router._handle_ci(db, GithubEventKind.WORKFLOW_RUN, workflow)
    assert link.ci_state == "failure"


async def test_deleted_vcs_env_seed_stays_deleted(world, monkeypatch):
    from contextlib import asynccontextmanager
    from radd.config import settings
    from radd.modules.forgejo import service
    from radd.modules.forgejo.models import ForgejoConnection
    from sqlalchemy import delete

    db, admin, project = world
    await db.execute(delete(ForgejoConnection))

    @asynccontextmanager
    async def factory():
        yield db

    async def commit():
        await db.flush()

    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(db, "commit", commit)
    monkeypatch.setattr(settings, "forgejo_webhook_secret", "review-seed")
    await service.seed_from_env()
    first = await db.scalar(select(ForgejoConnection))
    await service.delete_connection(db, first.id)
    await service.seed_from_env()
    second = await db.scalar(select(ForgejoConnection))
    assert second is None


async def test_state_gate_does_not_run_false_branch_when_subject_matches(world):
    from radd.modules.workflow.models import State

    db, admin, project = world
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Gate semantics"), admin
    )
    target = await items.require_item(db, item.id)
    category = (await db.get(State, target.state_id)).category
    automation = await rule(
        db,
        admin,
        [
            trigger(),
            {
                "id": "g",
                "kind": "gate",
                "type": "gate.state_category",
                "params": {"categories": [category]},
            },
            {
                "id": "w",
                "kind": "action",
                "type": "action.send_webhook",
                "params": {"url": "https://example.test/false-branch"},
            },
        ],
        [wire("t", "g"), wire("g", "w", "false")],
    )
    result = await engine.preview(db, automation, item.id)
    assert not result.would_apply


async def test_preview_explicitly_reports_created_branches_as_unavailable(world):
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Original"), admin)
    automation = await rule(
        db,
        admin,
        [
            trigger(),
            {
                "id": "c",
                "kind": "action",
                "type": "action.create_item",
                "params": {"project": project.key, "title": "Followup"},
            },
            {"id": "f", "kind": "action", "type": "action.set_flag", "params": {"flagged": True}},
        ],
        [wire("t", "c"), wire("c", "f", "created")],
    )
    preview = await engine.preview(db, automation, item.id)
    assert [p.node_id for p in preview.would_apply] == ["c"]
    assert any("not simulated" in warning for warning in preview.dropped)
    await engine.run_manual(db, automation, item.id, start_node_id="t")
    created = await db.scalar(
        select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.title == "Followup")
    )
    assert created is not None and created.flagged


async def test_repo_scope_and_deleting_repo_stop_ingestion(world):
    from radd.modules.gitlab import service, parsing
    from radd.modules.gitlab.schemas import ConnectionCreate, RepoCreate
    from radd.modules.projects import service as projects
    from radd.modules.projects.schemas import ProjectCreate

    db, admin, project = world
    other = await projects.create_project(
        db, ProjectCreate(key=f"OT{uuid.uuid4().hex[:5].upper()}", name="Other project")
    )
    item = await items.create_item(
        db, ItemCreate(project_id=other.id, title="Outside mapped project"), admin
    )
    connection = await service.create_connection(
        db,
        ConnectionCreate(
            name=uuid.uuid4().hex, base_url="https://git.test", webhook_secret="review-scope"
        ),
    )
    name = f"team/{uuid.uuid4().hex}"
    repo = await service.create_repo(
        db, RepoCreate(connection_id=connection.id, full_name=name, project_id=project.id)
    )
    payload = {
        "project": {"path_with_namespace": name, "web_url": f"https://git.test/{name}"},
        "ref": "refs/heads/main",
        "commits": [
            {
                "id": "abc",
                "message": f"Fix {other.key}-{item.number}",
                "url": "https://git.test/commit/abc",
            }
        ],
    }
    assert await service.resolve_for_payload(db, payload, "review-scope") is not None
    repo.link_all_projects = False
    await db.flush()
    links = await receiving.link_planned(
        db,
        parsing.plan_push(payload),
        provider=VcsProvider.GITLAB,
        actor_id=admin.id,
        connection_id=connection.id,
        repo=repo,
    )
    assert not links
    repo.enabled = False
    await db.flush()
    assert await service.resolve_for_payload(db, payload, "review-scope") is None
    await service.delete_repo(db, repo.id)
    resolved = await service.resolve_for_payload(db, payload, "review-scope")
    assert resolved is None


async def test_missing_owner_records_failure_until_explicit_adoption(world):
    from radd.modules.automations.schemas import RuleUpdate

    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Owner"), admin)
    automation = await rule(
        db,
        admin,
        [
            trigger(),
            {"id": "a", "kind": "action", "type": "action.set_flag", "params": {"flagged": True}},
        ],
        [wire("t", "a")],
    )
    automation.created_by_id = uuid.uuid4()
    await db.flush()
    await engine.run_manual(db, automation, item.id, start_node_id="t")
    run = await db.scalar(select(AutomationRun).where(AutomationRun.automation_id == automation.id))
    assert run.status == "failed" and "execution account" in run.error
    assert not (await items.require_item(db, item.id)).flagged
    await automations.update_rule(db, automation.id, RuleUpdate(adopt_execution=True), admin.id)
    await engine.run_manual(db, automation, item.id, start_node_id="t")
    assert (await items.require_item(db, item.id)).flagged


async def test_act_as_keeps_account_identity_when_email_changes(world):
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Identity"), admin)
    automation = await rule(
        db,
        admin,
        [
            trigger(),
            {
                "id": "a",
                "kind": "action",
                "type": "action.set_flag",
                "params": {"flagged": True, "act_as": admin.email},
            },
        ],
        [wire("t", "a")],
    )
    assert automation.nodes[1]["params"]["act_as_id"] == str(admin.id)
    old_email = admin.email
    admin.email = f"renamed-{uuid.uuid4().hex}@example.test"
    db.add(User(email=old_email, name="Replacement", instance_role="member"))
    await db.flush()
    await engine.run_manual(db, automation, item.id, start_node_id="t")
    assert (await items.require_item(db, item.id)).flagged


async def test_ci_does_not_cross_connections_or_accept_an_older_commit(world):
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="CI host"), admin)
    first, second = uuid.uuid4(), uuid.uuid4()
    links = [
        await vcs.upsert_vcs_link(
            db,
            item.id,
            provider=VcsProvider.GITHUB,
            ref_type=VcsRefType.BRANCH,
            connection_id=connection,
            external_id="branch:team/repo:main",
            title="main",
            url=f"https://host{index}/main",
        )
        for index, connection in enumerate([first, second])
    ]
    common = dict(
        provider=VcsProvider.GITHUB, external_ids=["branch:team/repo:main"], connection_id=second
    )
    await vcs.set_ci_state(
        db,
        **common,
        ci_state="success",
        run_id=200,
        head_sha="new",
        source_started_at="2026-09-25T12:00:00Z",
    )
    assert links[0].ci_state == "" and links[1].ci_state == "success"
    assert not await vcs.set_ci_state(
        db,
        **common,
        ci_state="failure",
        run_id=100,
        head_sha="old",
        source_started_at="2026-09-24T12:00:00Z",
    )
    # Even a different stream cannot repaint an older commit as current.
    assert not await vcs.set_ci_state(
        db,
        **common,
        ci_state="failure",
        report_key="old-job",
        run_id=999,
        head_sha="old",
        source_started_at="2026-09-24T12:00:00Z",
    )
    assert links[1].ci_state == "success"


async def test_script_credentials_do_not_commit_callers_changes(world, monkeypatch):
    from sqlalchemy import delete
    from radd.modules.scripts import runner, service

    db, admin, project = world
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as setup:
        actor = User(
            email=f"script-{uuid.uuid4().hex}@example.test",
            name="Script actor",
            instance_role="admin",
        )
        setup.add(actor)
        await setup.commit()
    try:
        item = await items.create_item(
            db, ItemCreate(project_id=project.id, title="Uncommitted script input"), admin
        )

        async def run(body, payload, **kwargs):
            async with maker() as observer:
                assert await observer.get(WorkItem, item.id) is None
                assert (
                    await observer.scalar(select(ApiToken).where(ApiToken.user_id == actor.id))
                    is not None
                )
            return runner.Outcome(True, result={})

        monkeypatch.setattr(runner, "run", run)
        assert (
            await service.run_body(
                db, "def main(ctx): return {}", {}, actor=actor, timeout=5, label="isolation"
            )
        ).ok
        async with maker() as observer:
            assert await observer.get(WorkItem, item.id) is None
            assert (
                await observer.scalar(select(ApiToken).where(ApiToken.user_id == actor.id)) is None
            )
    finally:
        async with maker() as cleanup:
            await cleanup.execute(delete(User).where(User.id == actor.id))
            await cleanup.commit()


async def test_preview_endpoint_uses_unsaved_graph_and_recorded_event(world):
    from radd.modules.automations.schemas import RuleTestRequest
    from radd.modules.events.models import Event

    router = importlib.import_module("radd.modules.automations.router")
    db, admin, project = world
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Draft preview"), admin
    )
    original = [
        trigger("item.created"),
        {"id": "a", "kind": "action", "type": "action.set_flag", "params": {"flagged": False}},
    ]
    automation = await rule(db, admin, original, [wire("t", "a")])
    event = await db.scalar(
        select(Event).where(Event.event_type == "item.created", Event.entity_id == str(item.id))
    )
    assert event is not None
    draft = [original[0], {**original[1], "params": {"flagged": True}}]
    result = await router._preview_draft(
        RuleTestRequest(nodes=draft, edges=[wire("t", "a")], event_id=event.id),
        db,
        admin,
        automation,
    )
    assert result.would_apply[0].params["flagged"] is True
    assert result.would_apply[0].resolves
    assert automation.nodes[1]["params"]["flagged"] is False
    assert not (await items.require_item(db, item.id)).flagged
    assert event.id in [
        row["id"] for row in await router.recorded_samples("item.created", db, admin)
    ]
