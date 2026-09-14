from radd.kernel import EventTypeSpec, RaddPlugin, SlqFieldSpec
from radd.kernel import CrudResourceSpec, ProjectPurgeSpec

from .router import router
from .types import ViewEntity, ViewEvent
from .slqfield import roadmap_member_item_ids
from . import subscribers  # noqa: F401  — registers the project-created seeding hook

from .service import _VIEW_SPEC

def _view_event(event_type: ViewEvent, label: str, entity: str, *, diff: bool = False):
    """RADD-1168: emitted since spec 15 and never registered. Not triggers."""
    return EventTypeSpec(
        event_type, label, "Views", has_changes=diff, trigger=False, entity_type=entity,
        subjects=("project",) if entity == ViewEntity.VIEW else (),
    )


plugin = RaddPlugin(
    name="views",
    event_types=(
        _view_event(ViewEvent.CREATED, "Saved view created", "view"),
        _view_event(ViewEvent.UPDATED, "Saved view updated", "view", diff=True),
        _view_event(ViewEvent.DELETED, "Saved view deleted", "view"),
        _view_event(ViewEvent.CARD_PRESET_CREATED, "Card preset created", "card_preset"),
        _view_event(ViewEvent.CARD_PRESET_UPDATED, "Card preset updated", "card_preset", diff=True),
        _view_event(ViewEvent.CARD_PRESET_DELETED, "Card preset deleted", "card_preset"),
    ),
    # RADD-892: `views.project_id` carries no ON DELETE CASCADE. Its members
    # cascade off the view row, so the view alone is enough.
    project_purges=(ProjectPurgeSpec(name="views", tables=("views",), order=20),),
    crud_resources=(
        CrudResourceSpec("view", "project", "saved views", "project.manage"),
        # Spec 109: the shared board-card layout preset library.
        CrudResourceSpec(
            "cardpreset", "global", "card layout presets", "global.manage",
            actions=("create", "read", "update", "delete"),
        ),
    ),
    # RADD-818: spec-92 resources ride the MANIFEST — the loader's clear()
    # wipes import-time registration, and the manifest is what survives it.
    access_resources=(_VIEW_SPEC,),
    description=(
        "Saved views (spec 10): named boards/lists/planning/queues over an SLQ "
        "query with group_by/swimlane_by axes; personal or workspace-shared; "
        "every read carries the composed GET /items query_string. POST "
        "/views/counts (spec 64) batches per-view membership counts for the "
        "sidebar queue badges. Every project ships with three plain seeded "
        "views (Board/List/Planning) created by the project-created hook — "
        "ordinary views, editable and deletable like any other."
    ),
    depends_on=("projects", "workflow", "items", "fields", "auth", "events", "access", "groups", "teams"),
    routers=(router,),
    slq_fields=(
        SlqFieldSpec(
            name="roadmap",
            label="Roadmap member of",
            item_ids=roadmap_member_item_ids,
        ),
    ),
)
