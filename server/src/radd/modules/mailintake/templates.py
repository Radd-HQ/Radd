"""The two messages the desk used to send unasked, as automation templates
(RADD-1318). `mail_send_ack` and `mail_send_resolved` are deleted: nothing
reaches a requester's mailbox that nobody switched on. Each opens as a disabled
draft; both send ON the issue's email thread, so a reply comes back to it."""

from radd.kernel import AutomationTemplateSpec

from .types import MailEvent

GROUP = "Email"

ACKNOWLEDGE_NEW_TICKETS = AutomationTemplateSpec(
    key="mailintake.acknowledge_new_tickets",
    name="Acknowledge new email tickets",
    description=(
        "When an email opens a new issue, reply to the sender with the issue key, "
        "on the issue's email thread so their reply comes back to it."
    ),
    group=GROUP,
    nodes=(
        {"id": "mail", "kind": "trigger", "type": "trigger.event", "params": {"event": MailEvent.RECEIVED.value}},
        # A reply appended to an existing issue fires the same event — an ack
        # per reply would be an autoresponder.
        {"id": "new", "kind": "gate", "type": "gate.payload",
         "params": {"path": "created_item", "operator": "eq", "value": "true"}},
        {"id": "ack", "kind": "action", "type": "action.send_email",
         "params": {
             "to": "{{payload.sender}}", "arity": "item", "thread": True,
             "subject": "[{{item.key}}] {{item.title}}",
             "body": (
                 "Your request has been received and is being tracked as {{item.key}}.\n"
                 "\n"
                 "We'll follow up by email. You can reply to this message to add details "
                 "— replies are attached to the ticket automatically (keep [{{item.key}}] "
                 "in the subject)."
             ),
         }},
    ),
    edges=(
        {"source": "mail", "port": "out", "target": "new"},
        {"source": "new", "port": "true", "target": "ack"},
    ),
)

TELL_REQUESTER_WHEN_RESOLVED = AutomationTemplateSpec(
    key="mailintake.tell_requester_when_resolved",
    name="Tell the requester when resolved",
    description=(
        "When an issue moves into a done state, email the person whose mail opened it. "
        "Skipped when the issue has no email contact."
    ),
    group=GROUP,
    nodes=(
        {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.updated"}},
        {"id": "moved", "kind": "gate", "type": "gate.field_changed",
         "params": {"field": "state", "from_mode": "any", "from_values": [], "to_mode": "any", "to_values": []}},
        {"id": "done", "kind": "gate", "type": "gate.state_category", "params": {"categories": ["done"]}},
        {"id": "notice", "kind": "action", "type": "action.send_email",
         "params": {
             "to": "contact", "arity": "item", "thread": True,
             "subject": "[{{item.key}}] Your request has been resolved",
             "body": (
                 "Your request {{item.key}} — {{item.title}} — has been marked {{item.state}}.\n"
                 "\n"
                 "If it isn't sorted, reply to this email and the ticket picks up where it left off."
             ),
         }},
    ),
    edges=(
        {"source": "trg", "port": "out", "target": "moved"},
        {"source": "moved", "port": "true", "target": "done"},
        {"source": "done", "port": "true", "target": "notice"},
    ),
)

TEMPLATES = (ACKNOWLEDGE_NEW_TICKETS, TELL_REQUESTER_WHEN_RESOLVED)
