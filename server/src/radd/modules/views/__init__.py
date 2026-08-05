from radd.kernel import RaddPlugin, SlqFieldSpec

from .router import router
from .slqfield import roadmap_member_item_ids
from . import subscribers  # noqa: F401  — registers the project-created seeding hook

from .service import _VIEW_SPEC

plugin = RaddPlugin(
    name="views",
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
