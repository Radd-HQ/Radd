from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from .router import router, series_router
from .types import CycleEvent, SeriesEvent

plugin = RaddPlugin(
    name="cycles",
    description=(
        "Global cycles (iterations) spanning projects, with recurring "
        "series (per-label auto-provisioned drafts) and a Jira-style complete flow. "
        "Status (draft/upcoming/active/completed) is derived, never stored."
    ),
    depends_on=("projects", "auth", "events"),
    routers=(router, series_router),
    event_types=(
        EventTypeSpec(CycleEvent.CREATED, "Cycle created", "Cycles"),
        EventTypeSpec(CycleEvent.UPDATED, "Cycle updated", "Cycles"),
        EventTypeSpec(CycleEvent.COMPLETED, "Cycle completed", "Cycles"),
        EventTypeSpec(CycleEvent.DELETED, "Cycle deleted", "Cycles"),
        EventTypeSpec(SeriesEvent.CREATED, "Cycle series created", "Cycles"),
        EventTypeSpec(SeriesEvent.UPDATED, "Cycle series updated", "Cycles"),
        EventTypeSpec(SeriesEvent.DELETED, "Cycle series deleted", "Cycles"),
    ),
)
