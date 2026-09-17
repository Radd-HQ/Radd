"""The cache-first import pipeline (spec 100), end to end against a real database.

The whole point of the rebuild is that these steps are separable and repeatable:
profile a cached snapshot → decide every mapping → provision real targets → dry
run → import → relink → roll back. So this walks exactly that, and pins the
invariants each step exists for:

- the plan is pre-filled, and everything UNUSED defaults to ignore;
- the dry run writes NOTHING but predicts what the import will do;
- an import preserves Jira numbers, dates and authorship, and is SILENT;
- an unresolvable cross-project link parks as a pending ref and RESOLVES when its
  target is imported later — the thing spec 90 could never do;
- rollback puts the database back.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.db import SessionLocal
from radd.modules import workflow  # noqa: F401 — registers the default-state hook
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemKind, Priority
from radd.modules.jiraimport import rollback, runs
from radd.modules.jiraimport.models import (
    JiraConnection,
    JiraPlan,
    JiraRun,
    JiraSnapshot,
    JiraSnapshotIssue,
)
from radd.modules.jiraimport.plan import service as plan_service
from radd.modules.jiraimport.plan.schemas import PlanCreate
from radd.modules.jiraimport.types import (
    JiraAuthMode,
    RunKind,
    RunStage,
    SnapshotStage,
    UserAction,
    VocabAction,
)
from radd.modules.workflow.types import StateCategory


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# --- fixtures -----------------------------------------------------------------


def _issue(key, *, summary, type_name="Task", status="To Do", category="new",
           priority="P2", parent=None, links=None, comments=None, worklog=None,
           components=None, versions=None, cf=None):
    fields = {
        "summary": summary,
        "issuetype": {"name": type_name},
        "status": {"name": status, "statusCategory": {"key": category}},
        "priority": {"name": priority},
        "created": "2021-03-04T09:00:00.000+0000",
        "updated": "2022-06-07T11:00:00.000+0000",
        "assignee": {"name": "adela", "displayName": "Adela Nowak"},
        "reporter": {"name": "bruno", "displayName": "Bruno Costa"},
        "labels": ["imported"],
    }
    if parent:
        fields["parent"] = {"key": parent}
    if links:
        fields["issuelinks"] = links
    if comments:
        fields["comment"] = {
            "comments": comments, "total": len(comments), "maxResults": len(comments),
        }
    if worklog:
        fields["worklog"] = {"worklogs": [worklog], "total": 1, "maxResults": 1}
    if components:
        fields["components"] = [{"name": c} for c in components]
    if versions:
        fields["fixVersions"] = [{"name": v} for v in versions]
    if cf:
        fields.update(cf)
    return {"key": key, "id": key.split("-")[1], "fields": fields}


CATALOGS = {
    "fields": {
        "summary": {"name": "Summary", "schema_type": "string", "is_custom": False},
        "customfield_20": {
            "name": "Domain", "schema_type": "option", "schema_key": "", "is_custom": True,
        },
        "customfield_21": {
            "name": "Rank", "schema_type": "string",
            "schema_key": "com.pyxis.greenhopper.jira:gh-lexo-rank", "is_custom": True,
        },
        "customfield_22": {
            "name": "Never Used", "schema_type": "string", "is_custom": True,
        },
    },
    # Deliberately NOT the English defaults: a pass here proves nothing is hardcoded.
    "issue_types": [
        {"id": "1", "name": "Task"}, {"id": "2", "name": "Epic"},
        {"id": "3", "name": "Anomalie"}, {"id": "9", "name": "Never Used Type"},
    ],
    "statuses": [
        {"id": "1", "name": "To Do", "statusCategory": {"key": "new"}},
        {"id": "2", "name": "Rejeté", "statusCategory": {"key": "done"}},
        {"id": "8", "name": "Unused Status", "statusCategory": {"key": "new"}},
    ],
    "priorities": [{"id": "1", "name": "P1"}, {"id": "2", "name": "P2"}, {"id": "3", "name": "P3"}],
    "link_types": [
        {"id": "1", "name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
        {"id": "2", "name": "Implements", "inward": "is implemented by", "outward": "implements"},
    ],
    "resolutions": [],
    "option_sets": {},
    "versions": [{"id": "1", "name": "1.4.0"}],
    "components": [{"id": "1", "name": "API"}],
}


async def _admin(db) -> uuid.UUID:
    user = User(
        email=f"pipe-{uuid.uuid4().hex[:8]}@example.com",
        name="Pipeline Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.commit()
    return user.id


async def _snapshot(db, project_key: str, issues: list[dict]) -> uuid.UUID:
    connection = JiraConnection(
        name=f"c-{uuid.uuid4().hex[:8]}",
        base_url="https://jira.example.com",
        auth_mode=JiraAuthMode.PAT.value,
        credential="tok",
    )
    db.add(connection)
    await db.flush()
    snapshot = JiraSnapshot(
        connection_id=connection.id,
        name=f"{project_key} snapshot",
        jira_project_key=project_key,
        jql=f"project = {project_key}",
        stage=SnapshotStage.DONE.value,
        catalogs=CATALOGS,
        issue_count=len(issues),
    )
    db.add(snapshot)
    await db.flush()
    for issue in issues:
        db.add(
            JiraSnapshotIssue(
                snapshot_id=snapshot.id,
                jira_key=issue["key"],
                jira_id=issue["id"],
                payload=issue,
            )
        )
    await db.commit()
    return snapshot.id


async def _cleanup(keys: list[str]) -> None:
    async with SessionLocal() as s:
        for key in keys:
            proj = (await s.execute(text("SELECT id FROM projects WHERE key=:k"), {"k": key})).scalar()
            if not proj:
                continue
            items = "item_id IN (SELECT id FROM work_items WHERE project_id=:p)"
            await s.execute(
                text("DELETE FROM jira_pending_refs WHERE source_item_id IN "
                     "(SELECT id FROM work_items WHERE project_id=:p)"), {"p": proj})
            for t in ("worklogs", "item_web_links"):
                await s.execute(text(f"DELETE FROM {t} WHERE {items}"), {"p": proj})
            # RADD-717: comments are polymorphic now — `item_id` is gone, and the
            # parent type has to be part of the predicate.
            await s.execute(
                text("DELETE FROM comments WHERE entity_type = 'item' AND entity_id IN "
                     "(SELECT id FROM work_items WHERE project_id=:p)"), {"p": proj})
            await s.execute(
                text("DELETE FROM item_links WHERE source_item_id IN (SELECT id FROM work_items WHERE project_id=:p) "
                     "OR target_item_id IN (SELECT id FROM work_items WHERE project_id=:p)"), {"p": proj})
            await s.execute(text("DELETE FROM access_grants WHERE resource_type='view' AND resource_id IN (SELECT id::text FROM views WHERE project_id=:p)"), {"p": proj})
            await s.execute(
                text("DELETE FROM field_definitions WHERE id IN "
                     "(SELECT field_id FROM field_definition_projects WHERE project_id=:p)"), {"p": proj})
            for t in ("views", "forms", "releases", "work_items", "issue_types", "states",
                      "project_timelogging"):
                await s.execute(text(f"DELETE FROM {t} WHERE project_id=:p"), {"p": proj})
            await s.execute(text("DELETE FROM projects WHERE id=:p"), {"p": proj})
        await s.commit()


async def _plan_for(db, snapshot_id: uuid.UUID, project_key: str) -> JiraPlan:
    plan = await plan_service.create_plan(
        db,
        PlanCreate(
            name=f"plan-{uuid.uuid4().hex[:8]}",
            snapshot_id=snapshot_id,
            radd_project_key=project_key,
            radd_project_name=f"{project_key} imported",
        ),
    )
    await db.commit()
    return plan


async def _run(db, plan: JiraPlan, actor_id: uuid.UUID, kind: RunKind) -> JiraRun:
    run = JiraRun(
        plan_id=plan.id,
        snapshot_id=plan.snapshot_id,
        actor_id=actor_id,
        kind=kind.value,
        dry_run=kind is RunKind.DRY_RUN,
    )
    db.add(run)
    await db.commit()
    await runs.execute(run.id)
    async with SessionLocal() as s:
        return await s.get(JiraRun, run.id)


# --- the plan -----------------------------------------------------------------


async def test_a_plan_is_prefilled_from_the_cache_and_ignores_what_is_unused(db):
    """Every vocabulary comes back mapped, and anything the project never uses
    defaults to ignore — the "hidden and ignored unless used" rule."""
    key = f"PL{uuid.uuid4().hex[:4].upper()}"
    snapshot_id = await _snapshot(db, "SRC", [
        _issue("SRC-1", summary="One", priority="P1",
               cf={"customfield_20": {"value": "Platform"}}),
        _issue("SRC-2", summary="Two", type_name="Anomalie", status="Rejeté",
               category="done", priority="P3",
               cf={"customfield_20": {"value": "Pipeline"}}),
    ])
    try:
        plan = await _plan_for(db, snapshot_id, key)
        m = plan_service.mappings(plan)

        used_types = {e.jira: e for e in m.issue_types}
        assert used_types["Task"].action is VocabAction.CREATE
        assert used_types["Anomalie"].action is VocabAction.CREATE  # a non-English type
        assert used_types["Never Used Type"].action is VocabAction.IGNORE
        assert used_types["Epic"].kind is ItemKind.EPIC

        statuses = {e.jira: e for e in m.statuses}
        # Jira files "Rejeté" under its `done` category, and the suggestion follows
        # Jira rather than guessing at the word — retargeting it to `canceled` is
        # exactly the judgement only the admin can make.
        assert statuses["Rejeté"].category is StateCategory.DONE
        assert statuses["Unused Status"].action is VocabAction.IGNORE

        # Priorities map by Jira's severity ORDER, so P1/P2/P3 works with no
        # English table at all.
        priorities = {e.jira: e.priority for e in m.priorities}
        assert priorities["P1"] is Priority.BLOCKER
        assert priorities["P3"] is Priority.LOW

        fields = {e.jira_id: e for e in m.fields}
        assert fields["customfield_20"].action.value in ("create", "map")
        assert fields["customfield_21"].action.value == "ignore"  # gh-lexo-rank
        assert fields["customfield_22"].action.value == "ignore"  # unused
    finally:
        await _cleanup([key])


async def test_an_unrecognised_link_type_becomes_a_real_one(db):
    """Spec 90 knew three names and flattened everything else into `relates`,
    losing the relationship. Spec 91 made link types definable, so "Implements"
    can be created instead."""
    key = f"PL{uuid.uuid4().hex[:4].upper()}"
    snapshot_id = await _snapshot(db, "SRC", [
        _issue("SRC-1", summary="One", links=[
            {"type": {"name": "Implements", "outward": "implements", "inward": "is implemented by"},
             "outwardIssue": {"key": "SRC-2"}}]),
        _issue("SRC-2", summary="Two"),
    ])
    try:
        plan = await _plan_for(db, snapshot_id, key)
        by_name = {e.jira: e for e in plan_service.mappings(plan).link_types}
        assert by_name["Blocks"].key == "blocks"
        assert by_name["Implements"].action is VocabAction.CREATE
        assert by_name["Implements"].key == "implements"
    finally:
        await _cleanup([key])


# --- dry run ------------------------------------------------------------------


async def test_a_dry_run_predicts_the_import_and_writes_nothing(db):
    key = f"DR{uuid.uuid4().hex[:4].upper()}"
    actor_id = await _admin(db)
    snapshot_id = await _snapshot(db, "SRC", [
        _issue("SRC-1", summary="One"), _issue("SRC-2", summary="Two"),
    ])
    try:
        plan = await _plan_for(db, snapshot_id, key)
        run = await _run(db, plan, actor_id, RunKind.DRY_RUN)

        assert RunStage(run.stage) is RunStage.DONE
        assert run.counts.get("items") == 2
        assert len(run.report["rows"]) == 2
        assert {r["radd_key"] for r in run.report["rows"]} == {f"{key}-1", f"{key}-2"}
        # Nothing was written — not even the project it would create.
        async with SessionLocal() as s:
            assert (await s.execute(
                text("SELECT count(*) FROM projects WHERE key=:k"), {"k": key})).scalar() == 0
            assert (await s.execute(
                text("SELECT count(*) FROM jira_import_records WHERE run_id=:r"),
                {"r": run.id})).scalar() == 0
    finally:
        await _cleanup([key])


# --- import -------------------------------------------------------------------


async def test_an_import_preserves_keys_dates_and_authorship_and_is_silent(db):
    """The four fidelity guarantees, plus the one spec 90 could not offer at all:
    an import must not notify anyone or fire automation rules."""
    key = f"IM{uuid.uuid4().hex[:4].upper()}"
    actor_id = await _admin(db)
    snapshot_id = await _snapshot(db, "SRC", [
        _issue("SRC-7", summary="Seven", status="Rejeté", category="done", priority="P1",
               components=["API"], versions=["1.4.0"],
               comments=[{"id": "900", "body": "a note", "author": {"name": "adela"},
                          "created": "2021-05-05T10:00:00.000+0000"}]),
    ])
    try:
        plan = await _plan_for(db, snapshot_id, key)
        run = await _run(db, plan, actor_id, RunKind.IMPORT)
        assert RunStage(run.stage) is RunStage.DONE, run.problems

        async with SessionLocal() as s:
            item = await items_service.find_item_by_key(s, f"{key}-7")
            assert item is not None  # the Jira NUMBER is preserved 1:1
            assert item.title == "Seven"
            assert str(item.created_at).startswith("2021-03-04")  # the real age
            assert item.priority == Priority.BLOCKER.value  # P1, by Jira's order

            # Its events are SILENT, so nobody is notified about years-old work
            # and no automation rule rewrites the history being imported.
            rows = (await s.execute(
                text("SELECT silent FROM events WHERE entity_id=:i"), {"i": str(item.id)}
            )).scalars().all()
            assert rows and all(rows)

            # The comment kept its original author and date.
            author, created = (await s.execute(
                text("SELECT author_id, created_at FROM comments WHERE entity_type = 'item' AND entity_id = :i"),
                {"i": item.id})).first()
            assert author is not None and author != actor_id
            assert str(created).startswith("2021-05-05")
    finally:
        await _cleanup([key])


async def test_an_internal_jira_comment_imports_as_an_internal_comment(db):
    """RADD-1180: importing a JSM internal note (or a role-restricted comment) as a
    PUBLIC Radd comment publishes it to every project member — and on a spec-121
    public project, to the world. Asserted on the stored rows, because the leak is
    in the column, not in the draft."""
    key = f"IN{uuid.uuid4().hex[:4].upper()}"
    actor_id = await _admin(db)
    snapshot_id = await _snapshot(db, "SRC", [
        _issue("SRC-3", summary="Three", comments=[
            {"id": "910", "body": "for the customer", "author": {"name": "adela"},
             "created": "2021-05-05T10:00:00.000+0000"},
            {"id": "911", "body": "agent-only note", "author": {"name": "adela"},
             "created": "2021-05-05T10:05:00.000+0000", "jsdPublic": False},
            {"id": "912", "body": "administrators only", "author": {"name": "adela"},
             "created": "2021-05-05T10:06:00.000+0000",
             "visibility": {"type": "role", "value": "Administrators"}},
        ]),
    ])
    try:
        plan = await _plan_for(db, snapshot_id, key)
        dry = await _run(db, plan, actor_id, RunKind.DRY_RUN)
        assert dry.counts["comments"] == 2
        assert any(p["kind"] == "comment_restricted" and p["subject"] == "SRC-3#912" for p in dry.problems)
        run = await _run(db, plan, actor_id, RunKind.IMPORT)
        assert run.counts["comments"] == 2
        assert any(p["kind"] == "comment_restricted" and p["subject"] == "SRC-3#912" for p in run.problems)
        assert RunStage(run.stage) is RunStage.DONE, run.problems

        async with SessionLocal() as s:
            item = await items_service.find_item_by_key(s, f"{key}-3")
            rows = dict((await s.execute(
                text("SELECT body, visibility FROM comments "
                     "WHERE entity_type = 'item' AND entity_id = :i"),
                {"i": item.id})).all())
            assert rows == {
                "for the customer": "public",
                "agent-only note": "internal",

            }
    finally:
        await _cleanup([key])


async def test_a_reimport_refreshes_rather_than_duplicating(db):
    key = f"RE{uuid.uuid4().hex[:4].upper()}"
    actor_id = await _admin(db)
    snapshot_id = await _snapshot(db, "SRC", [
        _issue("SRC-1", summary="First title",
               comments=[{"id": "901", "body": "once", "author": {"name": "adela"},
                          "created": "2021-05-05T10:00:00.000+0000"}]),
    ])
    try:
        plan = await _plan_for(db, snapshot_id, key)
        await _run(db, plan, actor_id, RunKind.IMPORT)
        # The cache changes (as a re-download would), then we import again.
        async with SessionLocal() as s:
            row = await s.get(JiraSnapshotIssue, (snapshot_id, "SRC-1"))
            payload = dict(row.payload)
            payload["fields"] = {**payload["fields"], "summary": "Second title"}
            row.payload = payload
            await s.commit()
        second = await _run(db, plan, actor_id, RunKind.IMPORT)

        async with SessionLocal() as s:
            item = await items_service.find_item_by_key(s, f"{key}-1")
            assert item.title == "Second title"
            assert (await s.execute(
                text("SELECT count(*) FROM work_items WHERE project_id=:p"),
                {"p": item.project_id})).scalar() == 1
            # Comments are deduplicated by Jira's own id — spec 90 stored no id,
            # so its only defence was to skip comments on a re-import entirely.
            assert (await s.execute(
                text("SELECT count(*) FROM comments WHERE entity_type = 'item' AND entity_id=:i"), {"i": item.id}
            )).scalar() == 1
        assert second.counts.get("items_updated") == 1
    finally:
        await _cleanup([key])


# --- cross-project relink -----------------------------------------------------


async def test_a_link_to_an_unimported_project_resolves_when_it_arrives(db):
    """The scenario spec 90 could never handle: import DEV, which links to TD;
    import TD later; the DEV→TD link becomes real."""
    dev = f"AA{uuid.uuid4().hex[:4].upper()}"
    other = f"BB{uuid.uuid4().hex[:4].upper()}"
    actor_id = await _admin(db)
    dev_snapshot = await _snapshot(db, "AAA", [
        _issue("AAA-1", summary="Needs the other project", links=[
            {"type": {"name": "Blocks", "outward": "blocks", "inward": "is blocked by"},
             "outwardIssue": {"key": "BBB-5"}}]),
    ])
    other_snapshot = await _snapshot(db, "BBB", [_issue("BBB-5", summary="The target")])
    try:
        dev_plan = await _plan_for(db, dev_snapshot, dev)
        first = await _run(db, dev_plan, actor_id, RunKind.IMPORT)
        assert first.counts.get("links_pending") == 1

        async with SessionLocal() as s:
            source = await items_service.find_item_by_key(s, f"{dev}-1")
            pending = (await s.execute(
                text("SELECT target_jira_key, web_link_id FROM jira_pending_refs "
                     "WHERE source_item_id=:i"), {"i": source.id})).first()
            assert pending[0] == "BBB-5"
            assert pending[1] is not None  # a stand-in web link, so it is not lost

        # Now the other project arrives. Its own import relinks automatically.
        other_plan = await _plan_for(db, other_snapshot, other)
        second = await _run(db, other_plan, actor_id, RunKind.IMPORT)
        assert second.counts.get("relinked") == 1

        async with SessionLocal() as s:
            source = await items_service.find_item_by_key(s, f"{dev}-1")
            target = await items_service.find_item_by_key(s, f"{other}-5")
            link_type = (await s.execute(
                text("SELECT link_type FROM item_links WHERE source_item_id=:s AND target_item_id=:t"),
                {"s": source.id, "t": target.id})).scalar()
            assert link_type == "blocks"
            # The stand-in is gone, because the real link replaced it.
            assert (await s.execute(
                text("SELECT count(*) FROM item_web_links WHERE item_id=:i"), {"i": source.id}
            )).scalar() == 0
            assert (await s.execute(
                text("SELECT count(*) FROM jira_pending_refs WHERE source_item_id=:i"),
                {"i": source.id})).scalar() == 0
    finally:
        await _cleanup([dev, other])


# --- rollback -----------------------------------------------------------------


async def test_rollback_puts_the_database_back(db):
    key = f"RB{uuid.uuid4().hex[:4].upper()}"
    actor_id = await _admin(db)
    snapshot_id = await _snapshot(db, "SRC", [
        _issue("SRC-1", summary="One"), _issue("SRC-2", summary="Two"),
    ])
    try:
        plan = await _plan_for(db, snapshot_id, key)
        run = await _run(db, plan, actor_id, RunKind.IMPORT)

        async with SessionLocal() as s:
            fresh = await s.get(JiraRun, run.id)
            pre = await rollback.preflight(s, fresh)
            assert pre.total > 0
            assert pre.edited_since == []  # nobody has touched them
            result = await rollback.execute(
                s, fresh, include_schema=True, skip_edited=True
            )
            await s.commit()
        assert result.undone >= 2

        async with SessionLocal() as s:
            assert await items_service.find_item_by_key(s, f"{key}-1") is None
            assert (await s.execute(
                text("SELECT count(*) FROM projects WHERE key=:k"), {"k": key})).scalar() == 0
    finally:
        await _cleanup([key])


async def test_rollback_can_keep_the_provisioned_schema(db):
    """The common repair: undo the issues, fix the mapping, re-import — without
    re-provisioning the project and its fields."""
    key = f"RK{uuid.uuid4().hex[:4].upper()}"
    actor_id = await _admin(db)
    snapshot_id = await _snapshot(db, "SRC", [_issue("SRC-1", summary="One")])
    try:
        plan = await _plan_for(db, snapshot_id, key)
        run = await _run(db, plan, actor_id, RunKind.IMPORT)
        async with SessionLocal() as s:
            fresh = await s.get(JiraRun, run.id)
            await rollback.execute(s, fresh, include_schema=False, skip_edited=True)
            await s.commit()
        async with SessionLocal() as s:
            assert await items_service.find_item_by_key(s, f"{key}-1") is None
            assert (await s.execute(
                text("SELECT count(*) FROM projects WHERE key=:k"), {"k": key})).scalar() == 1
    finally:
        await _cleanup([key])


async def test_rollback_leaves_alone_anything_edited_since_the_import(db):
    """Destroying somebody's later work has to be a choice, not a surprise."""
    key = f"RE{uuid.uuid4().hex[:4].upper()}"
    actor_id = await _admin(db)
    snapshot_id = await _snapshot(db, "SRC", [_issue("SRC-1", summary="One")])
    try:
        plan = await _plan_for(db, snapshot_id, key)
        run = await _run(db, plan, actor_id, RunKind.IMPORT)
        async with SessionLocal() as s:
            item = await items_service.find_item_by_key(s, f"{key}-1")
            await s.execute(
                text("UPDATE work_items SET updated_at = now() + interval '1 hour' WHERE id=:i"),
                {"i": item.id})
            await s.commit()
        async with SessionLocal() as s:
            fresh = await s.get(JiraRun, run.id)
            pre = await rollback.preflight(s, fresh)
            assert len(pre.edited_since) == 1
            result = await rollback.execute(s, fresh, include_schema=True, skip_edited=True)
            await s.commit()
        assert any(p.kind.value == "rollback_blocked" for p in result.problems)
        async with SessionLocal() as s:
            assert await items_service.find_item_by_key(s, f"{key}-1") is not None
    finally:
        await _cleanup([key])


# --- mapping into an existing select whose options are missing values ----------


async def test_missing_select_options_are_added_when_asked_and_restored_on_rollback(db):
    """The live failure that motivated it: three show codes were not options on a
    curated multi-select, so seven issues silently lost the value. Ticking
    `extend_options` ADDS them; rollback puts the original list back."""
    from radd.modules.fields import service as fields_service
    from radd.modules.fields.schemas import FieldDefinitionCreate
    from radd.modules.fields.types import FieldType
    from radd.modules.jiraimport.types import FieldAction

    key = f"OP{uuid.uuid4().hex[:4].upper()}"
    actor_id = await _admin(db)
    # A curated select that predates the import and is missing one value.
    field_key = f"shows_{uuid.uuid4().hex[:6]}"
    definition = await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            key=field_key, name="Shows", type=FieldType.SELECT, options=["ALPHA", "BETA"]
        ),
    )
    await db.commit()
    field_id = definition.id

    snapshot_id = await _snapshot(db, "SRC", [
        _issue("SRC-1", summary="known", cf={"customfield_30": {"value": "ALPHA"}}),
        _issue("SRC-2", summary="unknown", cf={"customfield_30": {"value": "GAMMA"}}),
    ])
    async with SessionLocal() as s:
        snap = await s.get(JiraSnapshot, snapshot_id)
        cat = dict(snap.catalogs)
        cat["fields"] = {**cat["fields"], "customfield_30": {
            "name": "Shows", "schema_type": "option", "is_custom": True}}
        snap.catalogs = cat
        await s.commit()
    try:
        plan = await _plan_for(db, snapshot_id, key)
        mappings = plan_service.mappings(plan)
        row = next(f for f in mappings.fields if f.jira_id == "customfield_30")
        row.action = FieldAction.MAP
        row.target_key = field_key
        row.extend_options = True
        row.observed_values = ["ALPHA", "GAMMA"]
        async with SessionLocal() as s:
            fresh = await s.get(JiraPlan, plan.id)
            fresh.mappings = mappings.model_dump(mode="json")
            await s.commit()

        run = await _run(db, plan, actor_id, RunKind.IMPORT)
        assert RunStage(run.stage) is RunStage.DONE, run.problems

        async with SessionLocal() as s:
            after = await fields_service.get_field(s, field_id)
            assert after.options == ["ALPHA", "BETA", "GAMMA"]  # added, nothing lost
            # The value survived onto the issue instead of being dropped.
            item = await items_service.find_item_by_key(s, f"{key}-2")
            assert item.custom_fields.get(field_key) == "GAMMA"

        async with SessionLocal() as s:
            fresh_run = await s.get(JiraRun, run.id)
            result = await rollback.execute(
                s, fresh_run, include_schema=True, skip_edited=False
            )
            assert result.restored == 1, result.problems
            await s.commit()
        async with SessionLocal() as s:
            restored = await fields_service.get_field(s, field_id)
            assert restored.options == ["ALPHA", "BETA"]  # the curated list is back
    finally:
        await _cleanup([key])
        async with SessionLocal() as s:
            await s.execute(text("DELETE FROM field_definitions WHERE id=:i"), {"i": field_id})
            await s.commit()


# --- departed people keep their attribution ------------------------------------


async def test_an_issue_assigned_to_a_deactivated_person_still_imports(db):
    """A Jira project full of ex-employees is the normal case, and their history is
    the reason you are importing. Radd refuses to ASSIGN to a deactivated account —
    correctly, for new work — but an import restates history, so it is allowed to
    name someone who has since left."""
    key = f"LV{uuid.uuid4().hex[:4].upper()}"
    actor_id = await _admin(db)
    leaver = User(
        email=f"leaver-{uuid.uuid4().hex[:8]}@example.com",
        name="Departed Person",
        instance_role=InstanceRole.MEMBER.value,
        active=False,  # offboarded
    )
    db.add(leaver)
    await db.commit()
    leaver_id, leaver_email = leaver.id, leaver.email

    issue = _issue("SRC-1", summary="Owned by someone who left")
    issue["fields"]["assignee"] = {"name": "gone", "displayName": "Departed Person",
                                   "emailAddress": leaver_email}
    issue["fields"]["reporter"] = {"name": "gone", "displayName": "Departed Person",
                                   "emailAddress": leaver_email}
    snapshot_id = await _snapshot(db, "SRC", [issue])
    try:
        plan = await _plan_for(db, snapshot_id, key)
        row = next(u for u in plan_service.mappings(plan).users if u.jira_key == "gone")
        # Matched on email, flagged as deactivated — visible, not a surprise.
        assert row.action is UserAction.MATCH
        assert row.user_id == leaver_id
        assert row.matched_inactive is True
        assert "deactivated" in row.match_reason

        run = await _run(db, plan, actor_id, RunKind.IMPORT)
        assert RunStage(run.stage) is RunStage.DONE, run.problems
        async with SessionLocal() as s:
            item = await items_service.find_item_by_key(s, f"{key}-1")
            assert item is not None, "the issue must not be lost because its owner left"
            assert item.assignee_id == leaver_id
            assert item.reporter_id == leaver_id
            # The account stays deactivated — importing history must not silently
            # bring an offboarded person back into every assignee picker.
            departed = await s.get(User, leaver_id)
            assert departed.active is False
    finally:
        await _cleanup([key])
        async with SessionLocal() as s:
            await s.execute(text("DELETE FROM users WHERE id=:u"), {"u": leaver_id})
            await s.commit()


async def test_ordinary_creation_still_refuses_a_deactivated_assignee(db):
    """The escape hatch is for imports only — normal work must not be assignable
    to someone who has left."""
    from radd.exceptions import ConflictError
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate

    key = f"NA{uuid.uuid4().hex[:4].upper()}"
    admin_id = await _admin(db)
    actor = await db.get(User, admin_id)
    leaver = User(
        email=f"gone-{uuid.uuid4().hex[:8]}@example.com",
        name="Gone",
        instance_role=InstanceRole.MEMBER.value,
        active=False,
    )
    db.add(leaver)
    project = await projects_service.create_project(db, ProjectCreate(key=key, name="No assign"))
    await db.commit()
    # Captured before the rollback below expires the instance.
    leaver_id = leaver.id
    try:
        with pytest.raises(ConflictError):
            await items_service.create_item(
                db,
                ItemCreate(project_id=project.id, title="new work", assignee_id=leaver.id),
                actor,
            )
        await db.rollback()
    finally:
        await _cleanup([key])
        async with SessionLocal() as s:
            await s.execute(text("DELETE FROM users WHERE id=:u"), {"u": leaver_id})
            await s.commit()


async def test_historical_comment_audit_is_body_free_read_only_and_uses_exact_provenance(db):
    import copy
    import json
    from sqlalchemy.exc import DBAPIError
    from radd.modules.jiraimport.audit_comments import report_rows

    key = f"AU{uuid.uuid4().hex[:4].upper()}"
    actor_id = await _admin(db)
    raw = _issue('SRC-1', summary='History', comments=[
        {'id': str(i), 'body': f'secret-body-{i}', 'author': {'name': 'adela'}}
        for i in range(1, 6)
    ])
    snapshot_id = await _snapshot(db, 'SRC', [raw])
    try:
        plan = await _plan_for(db, snapshot_id, key)
        run = await _run(db, plan, actor_id, RunKind.IMPORT)
        # Reconstruct the pre-fix situation: rows were created public even
        # though the captured source had internal/restricted audiences.
        historical = copy.deepcopy(raw)
        source_comments = historical['fields']['comment']['comments']
        source_comments[0]['jsdPublic'] = False
        source_comments[1]['visibility'] = {'type': 'group', 'value': 'private-team'}
        source_comments.pop(3)  # source missing -> unknown, never safe
        async with SessionLocal() as s:
            snapshot = await s.get(JiraSnapshotIssue, (snapshot_id, 'SRC-1'))
            snapshot.payload = historical
            await s.execute(text("DELETE FROM comments WHERE body='secret-body-5'"))
            await s.commit()
        async with SessionLocal() as s:
            await s.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            rows = [row async for row in report_rows(s, [run.id])]
            by_source = {row['source']: row for row in rows}
            assert {key: row['action'] for key, row in by_source.items()} == {
                'SRC-1#1': 'make_internal',
                'SRC-1#2': 'review_restricted_audience',
                'SRC-1#3': 'no_change_indicated',
                'SRC-1#4': 'source_unavailable',
                'SRC-1#5': 'target_missing',
            }
            assert all(row['comment_id'] for row in rows)
            assert by_source['SRC-1#2']['source_restriction']['value'] == 'private-team'
            assert 'secret-body' not in json.dumps(rows)
            # Prove the report runs under PostgreSQL's write prohibition.
            with pytest.raises(DBAPIError):
                await s.execute(text("UPDATE comments SET visibility='internal' WHERE body='secret-body-1'"))
            await s.rollback()
        again = await _run(db, plan, actor_id, RunKind.IMPORT)
        assert any(p['kind'] == 'comment_restricted' for p in again.problems)
        async with SessionLocal() as s:
            assert await s.scalar(text("SELECT visibility FROM comments WHERE body='secret-body-1'")) == 'public'
            # Removing a snapshot never turns an unauditable run into a clean bill.
            snapshot = await s.get(JiraSnapshot, snapshot_id)
            await s.delete(snapshot)
            await s.commit()
            rows = [row async for row in report_rows(s, [run.id])]
            assert all(row['action'] in ('source_unavailable', 'target_missing') for row in rows)
    finally:
        await _cleanup([key])


@pytest.mark.parametrize("preimport", [False, True])
async def test_native_team_mapping_dry_run_reimport_and_rollback(db, preimport):
    from radd.modules.jiraimport.schemas import FieldMappingEntry
    from radd.modules.jiraimport.types import BuiltinTarget, FieldAction
    key = f"TM{uuid.uuid4().hex[:4].upper()}"
    team_name = f"Domain-{uuid.uuid4().hex[:8]}"
    actor = await _admin(db)
    snapshot = await _snapshot(db, 'SRC', [
        _issue('SRC-1', summary='One', cf={'customfield_domain': {'value': 'Pipeline'}}),
        _issue('SRC-2', summary='Two', cf={'customfield_domain': {'value': 'Pipeline'}}),
    ])
    plan = await _plan_for(db, snapshot, key)
    try:
        if preimport:
            await _run(db, plan, actor, RunKind.IMPORT)  # Previously imported without a team.
        mappings = plan_service.mappings(plan)
        mappings.fields = [m for m in mappings.fields if m.jira_id != 'customfield_domain']
        mappings.fields.append(FieldMappingEntry(jira_id='customfield_domain', jira_name='Domain',
            action=FieldAction.NATIVE, builtin_target=BuiltinTarget.TEAM,
            value_map={'Pipeline': team_name}))
        plan.mappings = mappings.model_dump(mode='json')
        await db.commit()
        dry = await _run(db, plan, actor, RunKind.DRY_RUN)
        assert dry.counts.get('teams_created') == 1, (dry.counts, dry.problems)
        assert await db.scalar(text('SELECT count(*) FROM teams WHERE name=:n'), {'n': team_name}) == 0
        imported = await _run(db, plan, actor, RunKind.IMPORT)
        assert imported.stage == RunStage.DONE.value, imported.problems
        async with SessionLocal() as s:
            team = await s.scalar(text('SELECT id FROM teams WHERE name=:n'), {'n': team_name})
            for number in [1, 2]:
                assert (await items_service.find_item_by_key(s, f'{key}-{number}')).team_id == team
            result = await rollback.execute(s, await s.get(JiraRun, imported.id), include_schema=True, skip_edited=False)
            assert not result.problems
            await s.commit()
            restored = await items_service.find_item_by_key(s, f'{key}-1')
            assert (restored is not None and restored.team_id is None) if preimport else restored is None
            assert await s.scalar(text('SELECT count(*) FROM teams WHERE name=:n'), {'n': team_name}) == 0
    finally:
        await _cleanup([key])


async def test_unknown_comment_author_and_bad_comment_do_not_abort_import(db, monkeypatch):
    from radd.modules.comments import service as comments
    key = f"UA{uuid.uuid4().hex[:4].upper()}"
    actor = await _admin(db)
    snapshot = await _snapshot(db, 'SRC', [
        _issue('SRC-1', summary='One', comments=[
            {'id': '1', 'body': 'unknown author', 'created': '2018-04-25T05:46:56.000+0000'},
            {'id': '2', 'body': 'bad comment'},
            {'id': '3', 'body': 'known author', 'author': {'name': 'adela'}},
        ]), _issue('SRC-2', summary='After the failure'),
    ])
    plan = await _plan_for(db, snapshot, key)
    original = comments.create_comment
    async def failing(session, item_id, data, user):
        if data.body == 'bad comment':
            await session.execute(text('SELECT 1/0'))
        return await original(session, item_id, data, user)
    monkeypatch.setattr(comments, 'create_comment', failing)
    try:
        run = await _run(db, plan, actor, RunKind.IMPORT)
        assert run.stage == RunStage.DONE.value, run.problems
        assert run.counts['comments'] == 2
        assert any(p['kind'] == 'comment_failed' for p in run.problems)
        async with SessionLocal() as s:
            item = await items_service.find_item_by_key(s, f'{key}-1')
            rows = await comments.list_comments(s, item.id, await s.get(User, actor))
            assert len(rows) == 2
            assert rows[0].author is None
            assert rows[0].created_at.year == 2018
            assert rows[1].author is not None and rows[1].author.id != actor
            assert await items_service.find_item_by_key(s, f'{key}-2')
    finally:
        await _cleanup([key])
