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


#: What the retired googlechat plugin did from the environment (RADD-1319), as an
#: opt-in template. Chat and Slack incoming webhooks both take `{"text": …}`.
POST_TO_CHAT = AutomationTemplateSpec(
    key="automations.post_to_chat",
    name="Post new issues and SLA breaches to chat",
    description=(
        "Posts to a Google Chat (or Slack-style) incoming webhook when an issue is created "
        "or misses an SLA. Paste the space's webhook URL into both actions before enabling."
    ),
    group="Chat",
    nodes=(
        {"id": "created", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.created"}},
        {"id": "breached", "kind": "trigger", "type": "trigger.event", "params": {"event": "sla.breached"}},
        {"id": "post_new", "kind": "action", "type": "action.post_chat",
         "params": {"webhook_url": "https://chat.googleapis.com/v1/spaces/…",
                    "message": "New issue {{item.key}}: {{item.title}}\n{{item.url}}"}},
        {"id": "post_sla", "kind": "action", "type": "action.post_chat",
         "params": {"webhook_url": "https://chat.googleapis.com/v1/spaces/…",
                    "message": "SLA breached ({{payload.kind}}) on {{item.key}} — {{payload.policy_name}}\n{{item.url}}"}},
    ),
    edges=(
        {"source": "created", "port": "out", "target": "post_new"},
        {"source": "breached", "port": "out", "target": "post_sla"},
    ),
)

TEMPLATES: tuple[AutomationTemplateSpec, ...] = (POST_TO_CHAT,)
