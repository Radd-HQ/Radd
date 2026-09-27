from enum import StrEnum


class SlaEvent(StrEnum):
    POLICY_CREATED = "sla_policy.created"
    POLICY_UPDATED = "sla_policy.updated"
    POLICY_DELETED = "sla_policy.deleted"
    # entity_type=item, so these land in the item's history feed.
    BREACHED = "sla.breached"
    # Spec 69: fired ONCE per item/policy/kind when remaining time reaches the warning.
    DUE_SOON = "sla.due_soon"
    # RADD-1320: a target was met, once per item/policy/kind, with `on_time`.
    MET = "sla.met"


class SlaEntity(StrEnum):
    POLICY = "sla_policy"


class SlaViewType(StrEnum):
    """The saved-view types this plugin contributes (RADD-1396)."""

    #: The spec-64 triage queue: the host's list over `QUEUE_ROWS_PATH`, listed in the
    #: sidebar's Queues section with live counts. Stored as `views.view_type`.
    QUEUE = "slas.queue"


class SlaWidgetType(StrEnum):
    """The dashboard widget types this plugin contributes (RADD-1462) — the stored
    `widget_type`, and the `match` of the remote's `dashboard.widget` contribution."""

    #: The service-desk SLA report card over `GET /sla-report`. The value predates the
    #: contribution (it was a dashboards builtin): saved widgets keep working unchanged.
    REPORT = "report_sla"


#: The add-widget picker's name for the report widget.
REPORT_WIDGET_LABEL = "Service desk SLA"


#: The queue's rows: the `/items` paging contract, ordered by live SLA urgency (`queue.py`).
QUEUE_ROWS_PATH = "/sla-queue-items"
#: A queue starts with the reporter and the SLA timer beside the triage basics (spec 64).
QUEUE_COLUMNS = ("type", "labels", "reporter", "priority", "assignee", "slas.timer", "state")
#: Timers tick and breaches reorder the queue: re-read it every minute (spec 64).
QUEUE_REFRESH_SECONDS = 60
#: The project-settings page this plugin contributes: `/p/<KEY>/settings/sla` (spec 67).
SETTINGS_PAGE_SEGMENT = "sla"


class SlaKind(StrEnum):
    """The two timers a policy can set targets for."""

    RESPONSE = "response"
    RESOLUTION = "resolution"


class SlaMetOn(StrEnum):
    """What satisfies a target (RADD-1299); `DEFAULT_MET_ON` keeps the pre-RADD-1299
    rules. The reporter and the automation actor never satisfy a reply mode."""

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
#: A target's mode when the policy row stores none.
DEFAULT_MET_ON: dict[SlaKind, SlaMetOn] = {SlaKind.RESPONSE: SlaMetOn.FIRST_REPLY, SlaKind.RESOLUTION: SlaMetOn.DONE}

#: The csat plugin's registry name. The SLA report folds satisfaction ratings in
#: only while csat is LOADED (RADD-1386: `weak_depends=("csat",)`, checked at
#: request time, so a runtime disable drops the ratings without a restart).
CSAT_PLUGIN_ID = "csat"
