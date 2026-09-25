"""Enums and wire constants for the Alertmanager intake connector (spec 47,
rebuilt RADD-1317)."""

from enum import StrEnum


class AlertStatus(StrEnum):
    """Per-alert status in the Alertmanager webhook payload."""

    FIRING = "firing"
    RESOLVED = "resolved"


class AlertAction(StrEnum):
    """What the planner decided for one alert fingerprint."""

    CREATE = "create"  # new fingerprint, firing → create an issue
    STILL_FIRING = "still_firing"  # known fingerprint, firing again
    RESOLVED = "resolved"  # known fingerprint, resolved


class AlertTrigger(StrEnum):
    """RADD-1317: Alertmanager's OWN automation triggers, one per linked issue.
    The receiver records the alert and fires these — what an alert should DO to
    its issue (comment, label, move it) is an automation someone chose, starting
    from the templates this plugin ships."""

    FIRING = "alertmanager.alert.firing"
    REPEATED = "alertmanager.alert.repeated"
    RESOLVED = "alertmanager.alert.resolved"


class AlertmanagerEvent(StrEnum):
    """Receiver administration, audited (spec 123). The token appears only as
    "changed". Not triggers."""

    RECEIVER_CREATED = "alertmanager_receiver.created"
    RECEIVER_UPDATED = "alertmanager_receiver.updated"
    RECEIVER_DELETED = "alertmanager_receiver.deleted"


class AlertEntity(StrEnum):
    ALERT = "alert"
    RECEIVER = "alertmanager_receiver"


# Item titles are capped at 500 chars (items.schemas.ItemCreate).
TITLE_MAX_CHARS = 500
