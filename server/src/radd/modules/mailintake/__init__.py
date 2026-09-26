from radd.kernel import EntityLinkSpec
from radd.kernel import CapabilitySpec, EventTypeSpec, PluginUiManifest
from radd.kernel import RaddPlugin
from radd.kernel import SettingSpec

from . import dispatcher, registry, seeding
from .config_router import router as config_router
from .signature_router import router as signature_router
from .router import router
from . import subscribers  # noqa: F401 — RADD-1174: the project-teardown hooks
from .rules_router import router as rules_router
from .automation import RESOLUTION_NODE
from .types import MailEvent, OUTBOUND_CONSUMER_NAME

plugin = RaddPlugin(
    name="mailintake",
    entity_links=(
        EntityLinkSpec('mail_source', ('/settings/email',)),
        EntityLinkSpec('mail_sender', ('/settings/email',)),
        EntityLinkSpec('mail_rule', ('/settings/email',)),
    ),
    consumer_names=(OUTBOUND_CONSUMER_NAME,),
    consumer_descriptions=((OUTBOUND_CONSUMER_NAME, "Sends outbound mail replies"),),
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
    # csat (RADD-982/1368): it depends_on THIS module, so the resolution
    # notice's "yield to the survey" question can only be asked the deferred
    # way — and a disabled csat answering by absence is exactly right.
    weak_depends=("ai", "csat"),
    routers=(router, config_router, rules_router, signature_router),
    # The resolution notice as a node too, for rules that want it on their own
    # conditions; it shares `resolved.py`'s guards and wording.
    automation_nodes=(RESOLUTION_NODE,),
    # RADD-1368: what the desk sends a requester on its own. Settings on the
    # Email page, run by this module, OFF until someone switches them on.
    # `section="email"` lands them on Settings → Email (RADD-930); the project
    # scope renders on a project's General page.
    settings_keys=(
        SettingSpec(
            key="mail_send_ack",
            type="bool",
            scopes=("instance", "project"),
            label="Receipt for new email tickets",
            description=(
                "Reply to the sender when their email opens a new issue, on the issue's email "
                "thread so their reply comes back to it. Replies to an existing issue get no receipt."
            ),
            section="email",
        ),
        SettingSpec(
            key="mail_ack_body",
            type="string",
            scopes=("instance",),
            label="Receipt text",
            multiline=True,
            description=(
                "Plain-text body of the receipt. Tokens: {{key}}, {{title}}, {{link}}, "
                "{{requester_name}} — an unrecognised token is sent as written. Empty sends the default wording."
            ),
            section="email",
        ),
        SettingSpec(
            key="mail_send_resolved",
            type="bool",
            scopes=("instance", "project"),
            label="Resolution notice",
            description=(
                "Email an issue's external contacts when it moves into a done state. A project with "
                "satisfaction surveys on sends the survey instead, which already says the issue is resolved."
            ),
            section="email",
        ),
    ),
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
    ui=PluginUiManifest(remote="/plugins/mailintake/remoteEntry.js", ui_api_version="1.3.0"),
)
