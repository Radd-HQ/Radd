from radd.kernel import EntityLinkSpec, IntegrationSpec
from radd.kernel import CapabilitySpec, EventTypeSpec, NavItemSpec, PluginUiManifest
from radd.kernel import ConsumerResume, RaddPlugin
from radd.kernel import SettingSpec
from radd.kernel.sockets import Socket

from . import dispatcher, registry, seeding
from .config_router import router as config_router
from .signature_router import router as signature_router
from .router import router
from . import subscribers  # noqa: F401 — RADD-1174: the project-teardown hooks
from .rules_router import router as rules_router
from .automation import RESOLUTION_NODE
from .automation_email import NOTIFY_REPORTER_ON_DONE, SEND_EMAIL_NODE
from .notify_transport import NotificationMailTransport
from .types import MAIL_TRANSPORT_NAME, MailEvent, OUTBOUND_CONSUMER_NAME

plugin = RaddPlugin(
    name="mailintake",
    entity_links=(
        EntityLinkSpec('mail_source', ('/settings/email',)),
        EntityLinkSpec('mail_sender', ('/settings/email',)),
        EntityLinkSpec('mail_rule', ('/settings/email',)),
    ),
    consumer_names=(OUTBOUND_CONSUMER_NAME,),
    consumer_descriptions=((OUTBOUND_CONSUMER_NAME, "Sends outbound mail replies"),),
    # RADD-1372: re-enabled after weeks off, never mail requesters about the backlog.
    consumer_resume=((OUTBOUND_CONSUMER_NAME, ConsumerResume.HEAD),),
    core=False,  # optional plugin — disableable via the plugin manager
    description="Email in and out: turns incoming mail into issues and comments, and replies to requesters.",
    # attachments: mail parts become item attachments (RADD-956).
    # notify (RADD-1385): this plugin serves notify's MAIL_TRANSPORT socket in
    # notify's vocabulary, so the edge points here → core.
    depends_on=(
        "projects", "auth", "items", "comments", "automations", "events",
        "attachments", "settings", "workflow", "notify",
    ),
    # ai (RADD-961): the AI routing rule reaches it deferred, gated on
    # `feature_enabled`, so a disabled ai falls through to the next rule.
    # csat (RADD-982/1368): it depends_on THIS module, so "yield to the survey" is
    # asked deferred — a disabled csat answers by absence.
    weak_depends=("ai", "csat"),
    routers=(router, config_router, rules_router, signature_router),
    # RADD-1387: Send email is this plugin's node (key `action.send_email`, kept so
    # stored graphs load unchanged); disabled, it leaves the catalog.
    automation_nodes=(RESOLUTION_NODE, SEND_EMAIL_NODE),
    automation_templates=(NOTIFY_REPORTER_ON_DONE,),
    # RADD-1385: notification email rides this plugin through the kernel socket;
    # disabling it withdraws the transport and notify records email undeliverable.
    integrations=(
        IntegrationSpec(Socket.MAIL_TRANSPORT, MAIL_TRANSPORT_NAME, impl=NotificationMailTransport()),
    ),
    # RADD-1368: what the desk sends a requester on its own — OFF by default, on
    # Settings → Email (the project scope renders on a project's General page).
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
            page_scopes=("instance",),
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
            page_scopes=("instance",),
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
            page_scopes=("instance",),
        ),
    ),
    # Seed rows from env BEFORE the poller starts (RADD-958).
    on_startup=(seeding.seed_from_env, dispatcher.start),
    on_shutdown=(dispatcher.stop,),
    capabilities=(
        CapabilitySpec(
            "email_intake",
            "Email-to-issue intake",
            "connector",
            # Rows, not env: the snapshot the registry refreshes on every write.
            check=registry.capability_state,
        ),
        # RADD-1389: whoever owns the senders reports whether mail can go out.
        CapabilitySpec("outbound_mail", "Outbound email", "infra", check=registry.outbound_capability),
    ),
    # RADD-960: the mail channel's own events. `item_scoped` lets item actions
    # apply ("reopen when the customer replies"); `mail.dropped` has no item.
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
    # Federated UI: Settings → Email, the Monitoring mail card, the requester chip
    # in the issue rail, and a `content.body` claim folding signatures (RADD-1401).
    ui=PluginUiManifest(
        remote="/plugins/mailintake/remoteEntry.js", ui_api_version="2.0.0",
        nav=(NavItemSpec(key="email", label="Email", path="/settings/email", section="settings",
                         group="Server", icon="mail", order=45, requires_admin=True),),
    ),
)
