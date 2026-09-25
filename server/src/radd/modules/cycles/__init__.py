from radd.kernel import PluginUiManifest
from radd.kernel import EntityRefSpec, EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec

from . import service
from .router import router, series_router
from .types import CycleEvent, SeriesEvent

plugin = RaddPlugin(
    name="cycles",
    ui=PluginUiManifest(remote="/plugins/cycles/remoteEntry.js", ui_api_version="1.7.0"),
    crud_resources=(
        CrudResourceSpec(
            "cycle", "global", "cycles", "global.manage",
            actions=("create", "read", "update", "delete"),
        ),
    ),
    description=(
        "Cycles (sprints) with dates and optional recurring series."
    ),
    depends_on=("projects", "auth", "events", "settings", "teams"),
    weak_depends=("items", "timelogging"),
    routers=(router, series_router),
    # RADD-1320: a cycle is an event subject.
    entity_refs=(EntityRefSpec("cycle", service.cycle_ref, label="Cycle"),),
    event_types=(
        EventTypeSpec(CycleEvent.CREATED, "Cycle created", "Cycles", subjects=("cycle",)),
        EventTypeSpec(CycleEvent.UPDATED, "Cycle updated", "Cycles", has_changes=True, subjects=("cycle",)),
        EventTypeSpec(CycleEvent.COMPLETED, "Cycle completed", "Cycles", subjects=("cycle",)),
        EventTypeSpec(CycleEvent.DELETED, "Cycle deleted", "Cycles", subjects=("cycle",)),
        EventTypeSpec(SeriesEvent.CREATED, "Cycle series created", "Cycles"),
        EventTypeSpec(SeriesEvent.UPDATED, "Cycle series updated", "Cycles", has_changes=True),
        EventTypeSpec(SeriesEvent.DELETED, "Cycle series deleted", "Cycles"),
    ),
)
