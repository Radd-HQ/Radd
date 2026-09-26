"""The trigger kinds automations provides (RADD-1323) — manual, schedule,
validate — registered exactly as a plugin's would be. The scheduler fires
`schedule`, intake walks `validate`, `POST /automations/{id}/run` fires `manual`."""

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
    default_params={"targets": []},
    has_event=False,
    seeds=("item",),
)

TRIGGER_KINDS: tuple[TriggerKindSpec, ...] = (MANUAL_KIND, SCHEDULE_KIND, VALIDATE_KIND)
