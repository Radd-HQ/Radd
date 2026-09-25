from radd.kernel import CapabilitySpec, EventTypeSpec, PluginUiManifest
from radd.kernel import RaddPlugin

from . import dispatcher, registry, seeding
from .config_router import router as config_router
from .router import router
from . import subscribers  # noqa: F401 — RADD-1174: the project-teardown hooks
from .rules_router import router as rules_router
from .templates import TEMPLATES
from .automation import RESOLUTION_NODE
from .types import MailEvent, OUTBOUND_CONSUMER_NAME

plugin = RaddPlugin(
    name="mailintake",
    consumer_names=(OUTBOUND_CONSUMER_NAME,),
    core=False,  # optional plugin — disableable via the plugin manager
    description="Email in and out: turns incoming mail into issues and comments, and replies to requesters.",
    # attachments: mail parts become item attachments through the spec-102
    # polymorphic seam (RADD-956).
    # notify is GONE from this list (RADD-968): outbound used to mail notify's
    # watcher set, a second fan-out beside the one deciding the inbox. Users are
    # mailed by notify now, which reaches this module the other way — a deferred,
    # feature-detected call to `service.send_item_mail`.
    depends_on=(
        "projects", "auth", "items", "comments", "automations", "events",
        "attachments", "settings", "workflow",
    ),
    # RADD-961: the AI routing rule reaches `ai` DEFERRED and feature-detected —
    # the module is optional and disableable, and a missing one must fall through
    # to the next rule rather than cost a customer their email. Same edge
    # `attachments` declares for its own LLM storage rule.
    weak_depends=("ai",),
    routers=(router, config_router, rules_router),
    # RADD-1318: the receipt and the resolution notice, as opt-in automations.
    automation_templates=TEMPLATES,
    automation_nodes=(RESOLUTION_NODE,),
    # Seed rows from env BEFORE the poller starts, or the first tick finds
    # no sources on a fresh instance (RADD-958).
    on_startup=(seeding.seed_from_env, dispatcher.start),
    on_shutdown=(dispatcher.stop,),
    capabilities=(
        CapabilitySpec(
            "email_intake",
            "Email-to-issue intake",
            "connector",
            # Rows, not env — the sync check reads the snapshot the registry
            # refreshes on seed and on every write.
            check=registry.capability_state,
        ),
    ),
    # RADD-960: the mail channel's own events, so a rule can tell a customer's
    # REPLY from an agent typing in the UI. `item_scoped` is what makes SLQ
    # conditions and item actions apply — "reopen when the customer replies"
    # becomes one rule. `mail.dropped` is not item-scoped because by definition
    # there is no item.
    event_types=(
        EventTypeSpec(
            MailEvent.RECEIVED, "Email received", "Email", item_scoped=True,
            subjects=("item",),
        ),
        EventTypeSpec(
            MailEvent.SENT, "Email sent", "Email", item_scoped=True, subjects=("item",),
        ),
        EventTypeSpec(
            MailEvent.FAILED, "Email delivery failed", "Email", item_scoped=True,
            subjects=("item",), audited=False,
        ),
        EventTypeSpec(MailEvent.DROPPED, "Email discarded", "Email"),
        # Spec 123: mail configuration is audited with a diff; not a trigger.
        *(
            EventTypeSpec(
                event_type, label, "Admin",
                has_changes=event_type.endswith(".updated"), trigger=False, entity_type=entity,
            )
            for event_type, label, entity in (
                (MailEvent.SOURCE_CREATED, "Mail source created", "mail_source"),
                (MailEvent.SOURCE_UPDATED, "Mail source updated", "mail_source"),
                (MailEvent.SOURCE_DELETED, "Mail source deleted", "mail_source"),
                (MailEvent.SENDER_CREATED, "Mail sender created", "mail_sender"),
                (MailEvent.SENDER_UPDATED, "Mail sender updated", "mail_sender"),
                (MailEvent.SENDER_DELETED, "Mail sender deleted", "mail_sender"),
                (MailEvent.RULE_CREATED, "Mail routing rule created", "mail_rule"),
                (MailEvent.RULE_UPDATED, "Mail routing rule updated", "mail_rule"),
                (MailEvent.RULE_DELETED, "Mail routing rule deleted", "mail_rule"),
            )
        ),
    ),
    # Federated UI (spec 94): the external-requester chip in the issue rail
    # (web/remotes/mailintake), rendered by the host via the issue.panel.section slot.
    ui=PluginUiManifest(remote="/plugins/mailintake/remoteEntry.js", ui_api_version="1.0.0"),
)
