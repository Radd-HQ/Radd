from enum import StrEnum


class SlaEvent(StrEnum):
    POLICY_CREATED = "sla_policy.created"
    POLICY_UPDATED = "sla_policy.updated"
    POLICY_DELETED = "sla_policy.deleted"
    # Emitted with entity_type=item so it lands in the item's history feed.
    BREACHED = "sla.breached"
    # Spec 69: pre-breach warning — fired ONCE per item/policy/kind when the
    # remaining active time drops to the policy's warning_minutes. Payload
    # mirrors BREACHED plus remaining_seconds. Same entity_type=item.
    DUE_SOON = "sla.due_soon"


class SlaEntity(StrEnum):
    POLICY = "sla_policy"


class SlaKind(StrEnum):
    """The two timers a policy can set targets for."""

    RESPONSE = "response"
    RESOLUTION = "resolution"


class SlaMetOn(StrEnum):
    """RADD-1299 — what satisfies a target. Each target (response, resolution)
    picks one; the defaults are the two rules that were hardcoded before, so an
    existing policy keeps its exact behaviour.

    The reporter and the automation actor never satisfy a reply mode.
    """

    #: First public reply by anyone (response default — spec 30's rule).
    FIRST_REPLY = "first_reply"
    #: First public reply by a member of the target's chosen teams.
    REPLY_BY_TEAMS = "reply_by_teams"
    #: First public reply by a member of the ISSUE's team; no team = anyone.
    REPLY_BY_ASSIGNED_TEAM = "reply_by_assigned_team"
    #: First entry into a done-category state (resolution default).
    DONE = "done"
    #: First moment the issue is in one of the chosen states (creation counts).
    ENTERS_STATES = "enters_states"
    #: First moment the issue is NOT in one of the chosen states — "the clock
    #: runs while it sits in Triage". Created elsewhere = met at creation.
    LEAVES_STATES = "leaves_states"


REPLY_MODES = frozenset({SlaMetOn.FIRST_REPLY, SlaMetOn.REPLY_BY_TEAMS, SlaMetOn.REPLY_BY_ASSIGNED_TEAM})
STATE_MODES = frozenset({SlaMetOn.ENTERS_STATES, SlaMetOn.LEAVES_STATES})
