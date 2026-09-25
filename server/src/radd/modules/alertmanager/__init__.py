from radd.kernel import CapabilitySpec, CrudResourceSpec, EventTypeSpec, RaddPlugin

from . import service
from .admin_router import router as admin_router
from .models import AlertItem, AlertReceiver  # noqa: F401 — Alembic autogenerate
from .router import router
from .templates import TEMPLATES
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
    depends_on=("projects", "auth", "items", "events", "automations"),
    routers=(router, admin_router),
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
        # RADD-1317: the receiver acts on nothing itself — these are the triggers.
        _trigger(AlertTrigger.FIRING, "alert firing (new issue)"),
        _trigger(AlertTrigger.REPEATED, "alert firing again"),
        _trigger(AlertTrigger.RESOLVED, "alert resolved"),
    ),
    automation_templates=TEMPLATES,
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
