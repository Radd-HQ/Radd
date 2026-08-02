"""Enums and wire constants for the Alertmanager intake connector (spec 47)."""

from enum import StrEnum


class AlertStatus(StrEnum):
    """Per-alert status in the Alertmanager webhook payload."""

    FIRING = "firing"
    RESOLVED = "resolved"


class AlertAction(StrEnum):
    """What the planner decided for one alert fingerprint."""

    CREATE = "create"  # new fingerprint, firing → create an item
    STILL_FIRING = "still_firing"  # known fingerprint, firing → comment
    RESOLVED = "resolved"  # known fingerprint, resolved → comment (+ optional transition)


class AlertEntity(StrEnum):
    ALERT = "alert"


# Label applied to every alert-created item (resolved through the labels seam).
ALERT_LABEL = "alert"

# Item titles are capped at 500 chars (items.schemas.ItemCreate).
TITLE_MAX_CHARS = 500

# Comment bodies for the dedup follow-ups.
STILL_FIRING_TEMPLATE = "Alert still firing — {count} firing alert(s) in this notification group."
RESOLVED_COMMENT = "Alert resolved."
