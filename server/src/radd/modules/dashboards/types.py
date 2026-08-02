from enum import StrEnum

# Sharing levels are LITERALLY the spec-57 vocabulary — one enum, one wire
# format, one semantics (viewer | editor | owner-as-co-ownership).
from radd.modules.views.types import ShareLevel  # noqa: F401 — re-export


class WidgetType(StrEnum):
    """What a dashboard widget renders. Every member maps to an EXISTING read
    surface (spec 75 §2) — the widget's `config` names the scope, the frontend
    fetches through the ordinary endpoint, RBAC applies there."""

    REPORT_THROUGHPUT = "report_throughput"  # GET /reports/throughput
    REPORT_CFD = "report_cfd"  # GET /reports/cumulative-flow
    REPORT_TIME_IN_STATE = "report_time_in_state"  # GET /reports/time-in-state
    REPORT_VELOCITY = "report_velocity"  # GET /reports/velocity
    REPORT_BURNUP = "report_burnup"  # GET /reports/burnup
    REPORT_SLA = "report_sla"  # GET /reports/sla
    SLQ_COUNT = "slq_count"  # GET /items/count — a big-number card
    SLQ_LIST = "slq_list"  # GET /items?q=&limit= — compact item rows
    VIEW_COUNT = "view_count"  # POST /views/counts — a saved view's badge


class DashboardEvent(StrEnum):
    CREATED = "dashboard.created"
    UPDATED = "dashboard.updated"
    DELETED = "dashboard.deleted"


class DashboardEntity(StrEnum):
    DASHBOARD = "dashboard"
