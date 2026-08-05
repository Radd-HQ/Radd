from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec, ProjectPurgeSpec

from . import subscribers  # noqa: F401  — registers the project-created hook
from .router import router
from .types import TypeEvent

plugin = RaddPlugin(
    name="itemtypes",
    crud_resources=(
        CrudResourceSpec("issue_type", "project", "issue types", "project.manage"),
    ),
    # RADD-892: already cascades in the database; declared anyway so the purge
    # does not silently depend on a migration nobody re-reads. Order 75 — an
    # item's `type_id` is SET NULL, but items are gone by then either way.
    project_purges=(
        ProjectPurgeSpec(name="itemtypes", tables=("issue_types",), order=75),
    ),
    description="Per-project issue types (Bug/Task/Story/…) — the classification axis, "
    "orthogonal to the epic/issue/subtask hierarchy; seeds defaults on project creation (spec 51).",
    depends_on=("projects", "events", "auth"),
    routers=(router,),
    event_types=(
        EventTypeSpec(TypeEvent.CREATED, "Issue type created", "Admin"),
        EventTypeSpec(TypeEvent.UPDATED, "Issue type updated", "Admin"),
    ),
)
