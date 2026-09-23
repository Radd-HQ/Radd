from radd.kernel import EventTypeSpec, RaddPlugin

from .router import router
from . import subscribers  # noqa: F401 — RADD-1174: the project-teardown hooks
from .types import SettingEvent

plugin = RaddPlugin(
    name="settings",
    description="Settings that apply to every project, with per-project overrides.",
    depends_on=("events", "projects", "auth"),
    routers=(router,),
    # Spec 123: every effective setting change is an audit row with old → new.
    # Not an automation trigger — a rule that fires on its own configuration
    # changing is a loop nobody asked for.
    event_types=(
        EventTypeSpec(
            SettingEvent.CHANGED, "Setting changed", "Admin",
            has_changes=True, trigger=False, entity_type="scoped_setting",
        ),
    ),
)
