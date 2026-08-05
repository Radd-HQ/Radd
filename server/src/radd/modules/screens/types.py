"""Screen (field-layout) configuration types.

A *screen* decides, for a (project, issue-type) scope, where each arrangeable field
sits in the issue view: PRIMARY (always shown), SECONDARY (shown, but collapsed by
default in the compact peek panel), or HIDDEN (never rendered). It's presentation
only — it never affects validation, storage, or permissions.

The core identity fields (state, type, priority, title, description) are NOT
arrangeable — they always render. Everything else is: the optional builtins listed
here, plus every custom field (addressed as ``cf:<key>``).
"""

from enum import StrEnum


class ScreenPlacement(StrEnum):
    PRIMARY = "primary"  # always shown, top of the panel
    SECONDARY = "secondary"  # shown, collapsed by default in the peek panel
    HIDDEN = "hidden"  # never rendered


class ScreenBuiltinField(StrEnum):
    """Optional builtin fields/sections a screen can place. Bare tokens; custom fields
    are namespaced ``cf:<key>`` so the two never collide."""

    ASSIGNEE = "assignee"
    REPORTER = "reporter"
    TEAM = "team"
    CYCLE = "cycle"
    RELEASE = "release"
    START_DATE = "start_date"
    TARGET_DATE = "target_date"
    LABELS = "labels"
    SLA = "sla"
    TIME_TRACKING = "time_tracking"
    POINTS = "points"  # story points (spec 70) — rendered only where the project opts in


# Canonical order builtins fall in when a screen doesn't say otherwise (mirrors the
# pre-screens rail order). Custom fields follow, in their registry (created_at) order.
DEFAULT_BUILTIN_ORDER: tuple[ScreenBuiltinField, ...] = (
    ScreenBuiltinField.ASSIGNEE,
    ScreenBuiltinField.REPORTER,
    ScreenBuiltinField.TEAM,
    ScreenBuiltinField.CYCLE,
    ScreenBuiltinField.RELEASE,
    ScreenBuiltinField.START_DATE,
    ScreenBuiltinField.TARGET_DATE,
    ScreenBuiltinField.LABELS,
    ScreenBuiltinField.SLA,
    ScreenBuiltinField.TIME_TRACKING,
    ScreenBuiltinField.POINTS,
)

# Builtins that default to SECONDARY like custom fields (spec 70: points is
# opt-in per project, so it starts collapsed rather than crowding every rail).
SECONDARY_DEFAULT_BUILTINS = frozenset({ScreenBuiltinField.POINTS.value})

CUSTOM_FIELD_PREFIX = "cf:"


def is_custom_field(field: str) -> bool:
    return field.startswith(CUSTOM_FIELD_PREFIX)


def default_placement(field: str) -> ScreenPlacement:
    """Placement for a field a screen doesn't mention. Builtins stay visible (PRIMARY,
    preserving the pre-screens view); custom fields default to SECONDARY so the noisy
    long tail collapses in the peek panel without anyone configuring a thing."""
    if is_custom_field(field) or field in SECONDARY_DEFAULT_BUILTINS:
        return ScreenPlacement.SECONDARY
    return ScreenPlacement.PRIMARY


class ScreenEntity(StrEnum):
    SCREEN = "screen"


class ScreenEvent(StrEnum):
    UPDATED = "screen.updated"
