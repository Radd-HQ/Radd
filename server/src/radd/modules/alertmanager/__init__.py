from radd.kernel import CapabilitySpec, CrudResourceSpec, EventTypeSpec, NavItemSpec, PluginUiManifest, RaddPlugin

from . import service
from .admin_router import router as admin_router
from .models import AlertItem, AlertReceiver  # noqa: F401 — Alembic autogenerate
from .router import router
from .types import AlertEntity, AlertmanagerEvent, AlertTrigger


def _admin_event(event_type: AlertmanagerEvent, label: str) -> EventTypeSpec:
    """Spec 123: receiver administration is audited with a diff; not a trigger."""
    return EventTypeSpec(
        event_type, label, "Admin",
        has_changes=event_type.endswith(".updated"), trigger=False, entity_type=AlertEntity.RECEIVER,
    )


def _trigger(event_type: AlertTrigger, label: str) -> EventTypeSpec:
    return EventTypeSpec(event_type, f"Alertmanager: {label}", "Alertmanager", item_scoped=True, subjects=("item",))


plugin = RaddPlugin(
    name="alertmanager",
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Turns firing Prometheus Alertmanager alerts into issues, and offers firing, "
        "repeats and resolutions as automation triggers."
    ),
    # comments + workflow (RADD-1370): the receiver's own comment and
    # resolve-state settings.
    depends_on=("projects", "auth", "items", "events", "automations", "comments", "workflow"),
    routers=(router, admin_router),
    # RADD-1370: the settings page is this plugin's own remote; disabling the
    # plugin withdraws the page and its nav entry with it.
    ui=PluginUiManifest(
        remote="/plugins/alertmanager/remoteEntry.js", ui_api_version="1.13.0",
        nav=(NavItemSpec(key="alertmanager", label="Alertmanager", path="/settings/alertmanager",
                         section="settings", group="Server", icon="BellRing", order=99, requires_admin=True),),
    ),
    crud_resources=(
        CrudResourceSpec(
            "alertreceiver", "global", "Alertmanager receivers", "global.manage",
            actions=("create", "read", "update", "delete"),
        ),
    ),
    event_types=(
        _admin_event(AlertmanagerEvent.RECEIVER_CREATED, "Alertmanager receiver created"),
        _admin_event(AlertmanagerEvent.RECEIVER_UPDATED, "Alertmanager receiver updated"),
        _admin_event(AlertmanagerEvent.RECEIVER_DELETED, "Alertmanager receiver deleted"),
        # RADD-1317: the triggers, fired on every delivery; what the receiver
        # itself does is its own settings (RADD-1370).
        _trigger(AlertTrigger.FIRING, "alert firing (new issue)"),
        _trigger(AlertTrigger.REPEATED, "alert firing again"),
        _trigger(AlertTrigger.RESOLVED, "alert resolved"),
    ),
    # RADD_ALERTMANAGER_TOKEN (+ _PROJECT_KEY) seed ONE receiver row, once.
    on_startup=(service.seed_from_env,),
    capabilities=(
        CapabilitySpec(
            "alertmanager",
            "Alertmanager intake",
            "connector",
            check=lambda: {"enabled": service.active_receiver_count() > 0},
        ),
    ),
)
