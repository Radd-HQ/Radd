"""The behaviours Alertmanager used to run unasked, as automation templates
(RADD-1317): each opens as a disabled draft in the automation editor."""

from radd.kernel import AutomationTemplateSpec

from .types import AlertTrigger

GROUP = "Alertmanager"

COMMENT_ON_REPEAT_AND_RESOLVE = AutomationTemplateSpec(
    key="alertmanager.comment_on_repeat_and_resolve",
    name="Comment when an alert repeats or resolves",
    description="Adds a comment to the alert's issue each time it fires again, and when it resolves.",
    group=GROUP,
    nodes=(
        {"id": "again", "kind": "trigger", "type": "trigger.event", "params": {"event": AlertTrigger.REPEATED.value}},
        {"id": "done", "kind": "trigger", "type": "trigger.event", "params": {"event": AlertTrigger.RESOLVED.value}},
        {"id": "firing", "kind": "action", "type": "action.add_comment",
         "params": {"body": "Alert still firing — {{payload.firing_count}} firing alert(s) in this notification group.",
                    "visibility": "internal"}},
        {"id": "resolved", "kind": "action", "type": "action.add_comment",
         "params": {"body": "Alert resolved.", "visibility": "internal"}},
    ),
    edges=(
        {"source": "again", "port": "out", "target": "firing"},
        {"source": "done", "port": "out", "target": "resolved"},
    ),
)

MOVE_WHEN_RESOLVED = AutomationTemplateSpec(
    key="alertmanager.move_when_resolved",
    name="Move an alert's issue when it resolves",
    description="Transitions the alert's issue to a state when Alertmanager reports it resolved. Pick the state before enabling.",
    group=GROUP,
    nodes=(
        {"id": "done", "kind": "trigger", "type": "trigger.event", "params": {"event": AlertTrigger.RESOLVED.value}},
        {"id": "move", "kind": "action", "type": "action.set_state", "params": {"state": "Done"}},
    ),
    edges=({"source": "done", "port": "out", "target": "move"},),
)

LABEL_ALERT_ISSUES = AutomationTemplateSpec(
    key="alertmanager.label_alert_issues",
    name="Label issues created from alerts",
    description="Adds an `alert` label to every issue an alert creates.",
    group=GROUP,
    nodes=(
        {"id": "firing", "kind": "trigger", "type": "trigger.event", "params": {"event": AlertTrigger.FIRING.value}},
        {"id": "label", "kind": "action", "type": "action.add_label", "params": {"label": "alert"}},
    ),
    edges=({"source": "firing", "port": "out", "target": "label"},),
)

TEMPLATES = (COMMENT_ON_REPEAT_AND_RESOLVE, MOVE_WHEN_RESOLVED, LABEL_ALERT_ISSUES)
