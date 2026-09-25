"""Whole-automation templates (RADD-1316): what a module offers as a starting
point instead of running it unasked, and the ones `automations` itself ships.

A template is listed only when every node type and trigger event it names is
offered here — an Alertmanager template on an instance without Alertmanager
would open as a graph that cannot be saved.
"""

from __future__ import annotations

from radd.kernel.registry import registries
from radd.kernel.specs import AutomationTemplateSpec

from .catalog import triggers
from .types import AutomationNodeKind


def available(template: AutomationTemplateSpec) -> bool:
    nodes = registries.automation_nodes
    kinds = registries.trigger_kinds
    events = triggers()
    for node in template.nodes:
        if str(node.get("type")) not in nodes:
            return False
        if node.get("kind") == AutomationNodeKind.TRIGGER:
            event = str((node.get("params") or {}).get("event") or "")
            if event not in events and event not in kinds:
                return False
    return True


#: "Tell the reporter when their issue is done" — the kind of behaviour a
#: tracker might do unasked; here it is a starting point someone chooses.
NOTIFY_REPORTER_ON_DONE = AutomationTemplateSpec(
    key="automations.notify_reporter_on_done",
    name="Tell the reporter when their issue is done",
    description="When an issue moves into a done state, email its reporter.",
    group="Issues",
    nodes=(
        {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.updated"}},
        {"id": "moved", "kind": "gate", "type": "gate.field_changed",
         "params": {"field": "state", "from_mode": "any", "from_values": [], "to_mode": "any", "to_values": []}},
        {"id": "done", "kind": "gate", "type": "gate.state_category", "params": {"categories": ["done"]}},
        {"id": "mail", "kind": "action", "type": "action.send_email",
         "params": {"to": "reporter", "arity": "item",
                    "subject": "{{item.key}} is done",
                    "body": "Your issue {{item.key}} — {{item.title}} — is now {{item.state}}.\n{{item.url}}"}},
    ),
    edges=(
        {"source": "trg", "port": "out", "target": "moved"},
        {"source": "moved", "port": "true", "target": "done"},
        {"source": "done", "port": "true", "target": "mail"},
    ),
)

TEMPLATES: tuple[AutomationTemplateSpec, ...] = (NOTIFY_REPORTER_ON_DONE,)
