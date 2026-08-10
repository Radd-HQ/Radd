"""Cached Jira downloads (spec 100) — DB-backed with the Jira client stubbed.

The point of a snapshot is that everything after it is offline: profiling, the
dry run, the import, a re-import and relinking all read these rows. So the
invariants tested here are the ones the rest of the pipeline stands on:

- every matching issue is cached, across pages;
- a TRUNCATED comment/worklog list is backfilled — spec 90 took Jira's inline
  list at face value and silently dropped 67 of an issue's 87 comments;
- the instance's own vocabularies are captured, which is what lets the mapping
  step stop guessing from English names;
- delete really reclaims the space, including attachment blobs.

The job opens its OWN session and commits, so setup is committed here and
verification uses a fresh session.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.attachments import service as attachments_service
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.jiraimport.models import JiraConnection, JiraSnapshot
from radd.modules.jiraimport.snapshot import download, service as snapshot_service, store
from radd.modules.jiraimport.types import (
    JiraAuthMode,
    ProblemKind,
    SnapshotCatalog,
    SnapshotStage,
)


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def _issue(key: str, *, comments=None, comment_total=None, worklogs=None, worklog_total=None,
           attachment=None):
    fields = {
        "summary": f"Issue {key}",
        "issuetype": {"name": "Task"},
        "status": {"name": "To Do", "statusCategory": {"key": "new"}},
        "updated": "2026-02-01T09:00:00.000+0000",
    }
    if comments is not None:
        fields["comment"] = {
            "comments": comments,
            "total": comment_total if comment_total is not None else len(comments),
            "maxResults": len(comments),
        }
    if worklogs is not None:
        fields["worklog"] = {
            "worklogs": worklogs,
            "total": worklog_total if worklog_total is not None else len(worklogs),
            "maxResults": len(worklogs),
        }
    if attachment is not None:
        fields["attachment"] = attachment
    return {"key": key, "id": key.split("-")[1], "fields": fields}


async def _admin_and_connection(db) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"snap-{uuid.uuid4().hex[:8]}@example.com",
        name="Snapshot Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    connection = JiraConnection(
        name=f"stub-{uuid.uuid4().hex[:8]}",
        base_url="https://jira.example.com",
        auth_mode=JiraAuthMode.PAT.value,
        credential="tok",
    )
    db.add(connection)
    await db.commit()
    return user.id, connection.id


async def _snapshot(db, connection_id, actor_id, **overrides) -> uuid.UUID:
    row = JiraSnapshot(
        connection_id=connection_id,
        actor_id=actor_id,
        name="test",
        jira_project_key="SNAP",
        jql="project = SNAP",
        **overrides,
    )
    db.add(row)
    await db.commit()
    return row.id


async def _cleanup(snapshot_id: uuid.UUID) -> None:
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM jira_snapshots WHERE id=:i"), {"i": snapshot_id})
        await s.commit()


@pytest.fixture
def stub_catalogs(monkeypatch):
    """The instance vocabularies — deliberately NOT the English defaults spec 90
    assumed, so a test that passes proves nothing is hardcoded."""
    catalogs = {
        SnapshotCatalog.FIELDS.value: {
            "summary": {"name": "Summary", "schema_type": "string", "is_custom": False},
            "customfield_10020": {
                "name": "Sprint",
                "schema_type": "array",
                "schema_key": "com.pyxis.greenhopper.jira:gh-sprint",
                "is_custom": True,
            },
        },
        SnapshotCatalog.ISSUE_TYPES.value: [{"id": "1", "name": "Anomalie"}],
        SnapshotCatalog.STATUSES.value: [
            {"id": "9", "name": "Rejeté", "statusCategory": {"key": "done"}}
        ],
        SnapshotCatalog.PRIORITIES.value: [{"id": "1", "name": "P1"}],
        SnapshotCatalog.LINK_TYPES.value: [
            {"id": "1", "name": "Blocks", "inward": "is blocked by", "outward": "blocks"}
        ],
        SnapshotCatalog.RESOLUTIONS.value: [],
        SnapshotCatalog.OPTION_SETS.value: {},
        SnapshotCatalog.VERSIONS.value: [{"id": "1", "name": "1.4.0"}],
        SnapshotCatalog.COMPONENTS.value: [{"id": "1", "name": "API"}],
        "_failures": [],
    }
    monkeypatch.setattr(download, "_fetch_catalogs", lambda creds, key: dict(catalogs))
    return catalogs


# --- issues -------------------------------------------------------------------


async def test_a_download_caches_every_issue_across_pages(db, monkeypatch, stub_catalogs):
    """Paging is where an importer quietly loses rows, so prove all three land."""
    pages = [[_issue("SNAP-1"), _issue("SNAP-2")], [_issue("SNAP-3")], []]

    def fake_page(creds, jql, start_at, expand):
        index = start_at // 2
        return {"total": 3, "startAt": start_at, "issues": pages[index] if index < len(pages) else []}

    monkeypatch.setattr(download, "_search_page", fake_page)

    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, connection_id, actor_id)
    try:
        await download.execute(snapshot_id)
        async with SessionLocal() as s:
            snapshot = await snapshot_service.get_snapshot(s, snapshot_id)
            from sqlalchemy import select as _select

            from radd.modules.jiraimport.models import JiraSnapshotIssue

            keys = sorted(
                (
                    await s.execute(
                        _select(JiraSnapshotIssue.jira_key).where(
                            JiraSnapshotIssue.snapshot_id == snapshot_id
                        )
                    )
                ).scalars()
            )
        assert SnapshotStage(snapshot.stage) is SnapshotStage.DONE
        assert keys == ["SNAP-1", "SNAP-2", "SNAP-3"]
        assert snapshot.issue_count == 3
        assert snapshot.counts["issues"] == 3
        assert snapshot.counts["issues_total"] == 3
        assert snapshot.byte_size > 0  # sized, so the UI can offer to delete it
        assert snapshot.problems == []
    finally:
        await _cleanup(snapshot_id)


async def test_the_download_stabilises_an_unordered_jql():
    """Jira pages by offset, so an unstable sort skips and repeats rows under a
    long download. An explicit ORDER BY is left alone."""
    assert download._stable_jql("project = DEV") == "project = DEV ORDER BY created ASC"
    assert download._stable_jql("project = DEV ORDER BY key DESC") == "project = DEV ORDER BY key DESC"
    assert download._stable_jql("project = DEV order by key") == "project = DEV order by key"


async def test_the_instance_vocabularies_are_captured(db, monkeypatch, stub_catalogs):
    """Statuses/priorities/link types come from THIS Jira, which is what lets the
    mapping step present 'Rejeté' and 'P1' instead of failing an English lookup."""
    monkeypatch.setattr(
        download, "_search_page",
        lambda creds, jql, start_at, expand: {"total": 0, "issues": []},
    )
    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, connection_id, actor_id)
    try:
        await download.execute(snapshot_id)
        async with SessionLocal() as s:
            snapshot = await snapshot_service.get_snapshot(s, snapshot_id)
        assert [t["name"] for t in store.catalog(snapshot, SnapshotCatalog.ISSUE_TYPES)] == ["Anomalie"]
        assert [p["name"] for p in store.catalog(snapshot, SnapshotCatalog.PRIORITIES)] == ["P1"]
        assert [s_["name"] for s_ in store.catalog(snapshot, SnapshotCatalog.STATUSES)] == ["Rejeté"]
        assert [v["name"] for v in store.catalog(snapshot, SnapshotCatalog.VERSIONS)] == ["1.4.0"]
        # The sprint field is identified by Jira's stable schema key, not an id.
        fields = store.catalog(snapshot, SnapshotCatalog.FIELDS)
        assert fields["customfield_10020"]["schema_key"] == "com.pyxis.greenhopper.jira:gh-sprint"
    finally:
        await _cleanup(snapshot_id)


# --- the truncation fix -------------------------------------------------------


async def test_a_truncated_comment_list_is_backfilled(db, monkeypatch, stub_catalogs):
    """THE spec-90 data-loss bug: /search inlines 20 of 87 comments and reports
    total=87. Taking the inline list at face value lost 67 of them, silently."""
    inline = [{"id": str(i), "body": f"c{i}"} for i in range(20)]
    full = [{"id": str(i), "body": f"c{i}"} for i in range(87)]

    monkeypatch.setattr(
        download, "_search_page",
        lambda creds, jql, start_at, expand: {
            "total": 1,
            "issues": [_issue("SNAP-1", comments=inline, comment_total=87)] if start_at == 0 else [],
        },
    )
    monkeypatch.setattr(
        download, "_fetch_children",
        lambda creds, jobs: {f"{key}:{kind}": full for key, kind, _ in jobs},
    )

    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, connection_id, actor_id)
    try:
        await download.execute(snapshot_id)
        async with SessionLocal() as s:
            snapshot = await snapshot_service.get_snapshot(s, snapshot_id)
            row = await store.get_issue(s, snapshot_id, "SNAP-1")
        cached = row.payload["fields"]["comment"]
        assert len(cached["comments"]) == 87  # not 20
        assert cached["total"] == 87
        assert snapshot.counts["comments_backfilled"] == 67
        assert snapshot.counts["comments_backfilled_issues"] == 1
    finally:
        await _cleanup(snapshot_id)


async def test_an_untruncated_list_is_not_refetched(db, monkeypatch, stub_catalogs):
    """The backfill must cost nothing on the common case, or a big download pays
    an extra round trip per issue for no reason."""
    calls: list = []
    monkeypatch.setattr(
        download, "_search_page",
        lambda creds, jql, start_at, expand: {
            "total": 1,
            "issues": [_issue("SNAP-1", comments=[{"id": "1", "body": "only"}])]
            if start_at == 0
            else [],
        },
    )
    monkeypatch.setattr(
        download, "_fetch_children", lambda creds, jobs: calls.append(jobs) or {}
    )

    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, connection_id, actor_id)
    try:
        await download.execute(snapshot_id)
        assert calls == []
    finally:
        await _cleanup(snapshot_id)


async def test_a_failed_backfill_names_the_issue_it_affected(db, monkeypatch, stub_catalogs):
    """'Clear reasons for errors and which issues were affected' — a problem
    carries its subject, so the UI can group and list rather than truncate."""
    from radd.modules.jiraimport.client import JiraUnavailable

    monkeypatch.setattr(
        download, "_search_page",
        lambda creds, jql, start_at, expand: {
            "total": 1,
            "issues": [_issue("SNAP-42", comments=[{"id": "1"}], comment_total=99)]
            if start_at == 0
            else [],
        },
    )

    def boom(creds, jobs):
        raise JiraUnavailable("Jira said 500")

    monkeypatch.setattr(download, "_fetch_children", boom)

    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, connection_id, actor_id)
    try:
        await download.execute(snapshot_id)
        async with SessionLocal() as s:
            snapshot = await snapshot_service.get_snapshot(s, snapshot_id)
        assert SnapshotStage(snapshot.stage) is SnapshotStage.DONE  # not fatal
        problem = snapshot.problems[0]
        assert problem["kind"] == ProblemKind.COMMENTS_FETCH.value
        assert problem["subject"] == "SNAP-42"
        assert "Jira said 500" in problem["detail"]
    finally:
        await _cleanup(snapshot_id)


# --- failure + cancellation ---------------------------------------------------


async def test_an_unreachable_jira_fails_the_snapshot_with_a_reason(
    db, monkeypatch, stub_catalogs
):
    from radd.modules.jiraimport.client import JiraUnavailable

    monkeypatch.setattr(download, "PAGE_RETRY_DELAY", 0)

    def boom(creds, jql, start_at, expand):
        raise JiraUnavailable("could not reach Jira: timeout")

    monkeypatch.setattr(download, "_search_page", boom)

    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, connection_id, actor_id)
    try:
        await download.execute(snapshot_id)
        async with SessionLocal() as s:
            snapshot = await snapshot_service.get_snapshot(s, snapshot_id)
        assert SnapshotStage(snapshot.stage) is SnapshotStage.FAILED
        assert snapshot.finished_at is not None  # never left looking "still running"
        assert "timeout" in snapshot.problems[-1]["message"]
    finally:
        await _cleanup(snapshot_id)


async def test_a_download_without_a_connection_fails_loudly(db):
    """Rather than silently caching nothing."""
    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, None, actor_id)
    try:
        await download.execute(snapshot_id)
        async with SessionLocal() as s:
            snapshot = await snapshot_service.get_snapshot(s, snapshot_id)
        assert SnapshotStage(snapshot.stage) is SnapshotStage.FAILED
        assert "no longer exists" in snapshot.problems[-1]["message"]
    finally:
        await _cleanup(snapshot_id)


async def test_mark_interrupted_fails_a_download_the_process_abandoned(db):
    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, connection_id, actor_id, stage=SnapshotStage.ISSUES.value)
    try:
        await download.mark_interrupted()
        async with SessionLocal() as s:
            snapshot = await snapshot_service.get_snapshot(s, snapshot_id)
        assert SnapshotStage(snapshot.stage) is SnapshotStage.FAILED
        assert snapshot.finished_at is not None
    finally:
        await _cleanup(snapshot_id)


# --- lifecycle ----------------------------------------------------------------


async def test_an_incomplete_snapshot_cannot_be_planned_from(db):
    """A half-downloaded snapshot would import a partial project, so it is refused
    rather than quietly accepted."""
    from radd.exceptions import ConflictError

    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, connection_id, actor_id, stage=SnapshotStage.ISSUES.value)
    try:
        async with SessionLocal() as s:
            with pytest.raises(ConflictError):
                await snapshot_service.require_complete(s, snapshot_id)
    finally:
        await _cleanup(snapshot_id)


async def test_a_running_download_cannot_be_deleted(db):
    from radd.exceptions import ConflictError

    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, connection_id, actor_id, stage=SnapshotStage.ISSUES.value)
    try:
        async with SessionLocal() as s:
            with pytest.raises(ConflictError):
                await snapshot_service.delete_snapshot(s, snapshot_id)
    finally:
        await _cleanup(snapshot_id)


async def test_deleting_a_snapshot_reclaims_its_issues_and_its_blobs(
    db, monkeypatch, stub_catalogs
):
    """Delete has to genuinely free the space, or a cache-first importer just
    accumulates. Blobs live outside the database, so a cascade cannot reach them."""
    removed: list[str] = []

    async def fake_remove_blob(session, storage_name: str, *, host_id) -> None:
        removed.append(storage_name)

    async def fake_save_blob(session, upload, *, content_type: str):
        return attachments_service.BlobRef(
            storage_name=uuid.uuid4().hex, host_id=uuid.uuid4(), size_bytes=1234
        )

    monkeypatch.setattr(attachments_service, "remove_blob", fake_remove_blob)
    monkeypatch.setattr(attachments_service, "save_blob", fake_save_blob)
    monkeypatch.setattr(
        download, "_search_page",
        lambda creds, jql, start_at, expand: {
            "total": 1,
            "issues": [
                _issue(
                    "SNAP-1",
                    attachment=[
                        {"id": "900", "filename": "spec.pdf", "mimeType": "application/pdf",
                         "content": "https://jira.example.com/secure/attachment/900/spec.pdf"}
                    ],
                )
            ]
            if start_at == 0
            else [],
        },
    )
    monkeypatch.setattr(download, "_fetch_blobs", lambda creds, wanted: {w["id"]: b"pdf-bytes" for w in wanted})

    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, connection_id, actor_id, include_attachments=True)
    try:
        await download.execute(snapshot_id)
        async with SessionLocal() as s:
            snapshot = await snapshot_service.get_snapshot(s, snapshot_id)
            blobs = await store.blobs(s, snapshot_id)
        assert snapshot.counts["attachments"] == 1
        assert len(blobs) == 1 and blobs[0].filename == "spec.pdf"
        assert snapshot.byte_size >= 1234  # blob bytes counted in the displayed size

        async with SessionLocal() as s:
            await snapshot_service.delete_snapshot(s, snapshot_id)
            await s.commit()

        assert removed == [blobs[0].storage_name]  # the object store was cleaned
        async with SessionLocal() as s:
            assert await store.count_issues(s, snapshot_id) == 0
            assert await store.blobs(s, snapshot_id) == []
    finally:
        await _cleanup(snapshot_id)


async def test_a_failed_attachment_download_names_the_file_and_keeps_going(
    db, monkeypatch, stub_catalogs
):
    monkeypatch.setattr(
        download, "_search_page",
        lambda creds, jql, start_at, expand: {
            "total": 1,
            "issues": [
                _issue(
                    "SNAP-7",
                    attachment=[
                        {"id": "901", "filename": "big.mov", "mimeType": "video/quicktime",
                         "content": "https://jira.example.com/secure/attachment/901/big.mov"}
                    ],
                )
            ]
            if start_at == 0
            else [],
        },
    )
    monkeypatch.setattr(
        download, "_fetch_blobs", lambda creds, wanted: {w["id"]: "403 forbidden" for w in wanted}
    )

    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, connection_id, actor_id, include_attachments=True)
    try:
        await download.execute(snapshot_id)
        async with SessionLocal() as s:
            snapshot = await snapshot_service.get_snapshot(s, snapshot_id)
        assert SnapshotStage(snapshot.stage) is SnapshotStage.DONE
        problem = snapshot.problems[0]
        assert problem["kind"] == ProblemKind.ATTACHMENT_FETCH.value
        assert problem["subject"] == "SNAP-7 · big.mov"
    finally:
        await _cleanup(snapshot_id)


async def test_a_re_download_over_the_same_snapshot_refreshes_rather_than_collides(
    db, monkeypatch, stub_catalogs
):
    """Re-downloading is the repair path for a stale cache, so the second pass has
    to upsert."""
    summary = {"value": "first"}

    def fake_page(creds, jql, start_at, expand):
        if start_at:
            return {"total": 1, "issues": []}
        issue = _issue("SNAP-1")
        issue["fields"]["summary"] = summary["value"]
        return {"total": 1, "issues": [issue]}

    monkeypatch.setattr(download, "_search_page", fake_page)

    actor_id, connection_id = await _admin_and_connection(db)
    snapshot_id = await _snapshot(db, connection_id, actor_id)
    try:
        await download.execute(snapshot_id)
        summary["value"] = "second"
        async with SessionLocal() as s:
            snapshot = await snapshot_service.get_snapshot(s, snapshot_id)
            snapshot.stage = SnapshotStage.PENDING.value
            snapshot.finished_at = None
            await s.commit()
        await download.execute(snapshot_id)

        async with SessionLocal() as s:
            row = await store.get_issue(s, snapshot_id, "SNAP-1")
            assert await store.count_issues(s, snapshot_id) == 1  # not duplicated
        assert row.payload["fields"]["summary"] == "second"
    finally:
        await _cleanup(snapshot_id)
