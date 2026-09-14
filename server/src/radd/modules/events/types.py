from enum import StrEnum


class EventSource(StrEnum):
    """Who caused a row, as an audit filter (spec 123).

    Identity and causation are different questions (`Event.automated`): an
    automation acting AS a person leaves that person's actor_id, so "people"
    is actor-attributed AND not automated, "automations" is anything the
    engine caused whoever it ran as, and "system" is the actor-less rest —
    connectors, sweeps, the scheduler.
    """

    PEOPLE = "people"
    AUTOMATIONS = "automations"
    SYSTEM = "system"
