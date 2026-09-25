"""The trigger kinds automations itself provides, registered as `TriggerKindSpec`s
(RADD-1323) — a button, a clock, a draft being checked.

They were an enum of three sentinels with their handling scattered through the
service, the engine and the SPA's hardcoded templates. They are registered now
exactly as a plugin's kind would be, so the catalog serves them, the editor
builds its trigger menu from that, and "is there an event to read here" is the
spec's `has_event` rather than a list of sentinel names.

What each one DOES stays where it always was: the scheduler fires `schedule`,
intake walks `validate`, `POST /automations/{id}/run` fires `manual`. Their
write-time invariants (a schedule's shape, a validation binding's targets) are
checked by the service, which owns the state they project into.
"""

from __future__ import annotations

from radd.kernel.specs import TriggerKindSpec

from .types import AutomationTrigger

#: What a manual run may be pointed at. A `/`-menu run acts on an issue; a run
#: from the editor may target a page, which is what makes a page automation
#: testable at all.
MANUAL_SEEDS = ("item", "page")

MANUAL_KIND = TriggerKindSpec(
    key=AutomationTrigger.MANUAL.value,
    label="Manual (run from the / menu)",
    group="On demand",
    description="Runs when someone starts it — from an issue's / menu, or from the editor.",
    has_event=False,
    seeds=MANUAL_SEEDS,
)

SCHEDULE_KIND = TriggerKindSpec(
    key=AutomationTrigger.SCHEDULE.value,
    label="On a schedule",
    group="Scheduled",
    description=(
        "Runs on a clock, with no issues of its own — wire a Find issues node after it to "
        "select what each run acts on."
    ),
    # A schedule has no event and produces no items of its own (RADD-1265).
    default_params={"schedule": {"kind": "interval", "minutes": 30}},
    has_event=False,
)

VALIDATE_KIND = TriggerKindSpec(
    key=AutomationTrigger.VALIDATE.value,
    label="When someone submits (validate it)",
    group="Intake",
    description="Checks a draft before it becomes an issue.",
    # No targets by default: a trigger that governed something the moment it was
    # dropped could refuse a real submission before its author had finished.
    default_params={"targets": [], "mode": "advisory"},
    has_event=False,
    seeds=("item",),
)

TRIGGER_KINDS: tuple[TriggerKindSpec, ...] = (MANUAL_KIND, SCHEDULE_KIND, VALIDATE_KIND)
