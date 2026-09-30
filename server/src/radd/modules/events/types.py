from enum import StrEnum


class EventSource(StrEnum):
    """Who caused a row, as an audit filter (spec 123). The three partition the log.

    Identity and causation are different questions (`Event.automated`): an
    automation acting AS a person leaves that person's actor_id, so "people"
    is attributed to a PERSON's account and not automated; "automations" is
    anything the engine caused, whoever it ran as; and "system" is the rest —
    actor-less rows (sweeps, the scheduler) and rows written by a machine
    account (`auth.types.MACHINE_SOURCES`): connectors write as the built-in
    Automation account with `automated` false, and that is system, never
    people (RADD-1499).
    """

    PEOPLE = "people"
    AUTOMATIONS = "automations"
    SYSTEM = "system"
