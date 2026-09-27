"""RADD-1331: the trigger inspector's "What this event carries" lists an
event's DECLARED paths before it has ever fired.

It sampled only real events (RADD-921), so a trigger that had not fired here
yet — a fresh GitLab connection, an Alertmanager receiver — showed nothing, and
the paths a rule needs were discoverable only after the first event. The
declared half: the payload schema's paths, and each subject's ref fields read
from a real ref of that type (never an invented one).
"""

import importlib
import uuid

from sqlalchemy.dialects import postgresql

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.automations import samples
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

router = importlib.import_module("radd.modules.automations.router")


async def test_a_never_fired_trigger_lists_its_declared_paths(db, monkeypatch):
    admin = User(email=f"dp-{uuid.uuid4().hex[:8]}@example.com", name="Paths", instance_role="admin")
    db.add(admin)
    await db.flush()
    # A real item ref on this instance, so the `item` subject's fields are known.
    project = await projects_service.create_project(db, ProjectCreate(key=f"DP{uuid.uuid4().hex[:4].upper()}", name="Paths"))
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="a real one"), admin)

    async def nothing_recent(*args, **kwargs):
        return []  # as if this type had never fired here

    monkeypatch.setattr(router.events_service, "query_events", nothing_recent)
    read = await router.event_samples("gitlab.merge_request.merged", db, admin, limit=10)

    assert read.sampled == 0
    paths = {entry.path for entry in read.declared_paths}
    # From the declared schema…
    assert {"ref.number", "ref.source_branch", "author.username", "repo"} <= paths
    # …and the item subject's real ref fields, with this instance's values as examples.
    assert {"item.id", "item.key", "item.title"} <= paths
    ref = await events.latest_ref(db, "item")
    assert ref is not None and ref["id"] == str(item.id)


def test_schema_paths_walk_nested_objects_and_arrays():
    schema = {"type": "object", "properties": {
        "ci": {"type": "object", "properties": {"state": {"type": "string"}, "url": {"type": "string"}}},
        "changes": {"type": "array", "items": {"type": "object", "properties": {"field": {}, "to": {}}}},
        "repo": {"type": "string"},
    }}
    found = {entry.path: entry.repeated for entry in samples.schema_paths(schema)}
    assert found == {"ci.state": False, "ci.url": False, "changes.field": True, "changes.to": True, "repo": False}


def test_the_latest_ref_lookup_is_bounded_to_declaring_types_and_a_recent_window():
    """RADD-1452: `payload ? subject` has no index, so the lookup filters by the
    event types that declare the subject (indexed) and a window of recent ids
    (the primary key) — never a walk over the whole ledger."""
    from radd.kernel import load_plugins

    load_plugins(settings.modules)
    declaring = events.declaring_event_types("item")
    assert "item.updated" in declaring and "gitlab.merge_request.merged" in declaring
    assert not any(et.startswith(("page.", "comment.")) for et in declaring), "those carry no item ref"

    statement = events.latest_ref_statement("item", newest_id=1_000_000)
    compiled = statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    sql = str(compiled)
    assert "events.event_type IN (" in sql and "'item.updated'" in sql
    assert f"events.id > {1_000_000 - settings.events_latest_ref_scan_rows}" in sql
    assert "ORDER BY events.id DESC" in sql and "LIMIT 1" in sql

    # A subject no registered event type carries is not queried at all.
    assert events.latest_ref_statement("no_such_subject", newest_id=1_000_000) is None


async def test_an_undeclared_subject_and_an_empty_ledger_answer_none(db):
    assert await events.latest_ref(db, "no_such_subject") is None
