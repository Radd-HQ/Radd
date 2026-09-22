from radd.kernel import CapabilitySpec, EventTypeSpec, PluginUiManifest
from radd.kernel import RaddPlugin
from radd.kernel import SettingSpec

from . import dispatcher, registry, seeding
from .config_router import router as config_router
from .router import router
from . import subscribers  # noqa: F401 — RADD-1174: the project-teardown hooks
from .rules_router import router as rules_router
from .types import MailEvent, OUTBOUND_CONSUMER_NAME

plugin = RaddPlugin(
    name="mailintake",
    consumer_names=(OUTBOUND_CONSUMER_NAME,),
    core=False,  # optional plugin — disableable via the plugin manager
    description="Email-to-issue intake (spec 47) + the requester loop (spec 62): an "
    "IMAP poller turning unseen messages into items (or reply comments on a keyed "
    "subject) as the system actor, mail_contacts for external requesters, ack "
    "emails, an outbound consumer mailing public comments and resolution notices "
    "back to the contact, and the `service.send_item_mail` transport every module "
    "mails an issue through.",
    # attachments: mail parts become item attachments through the spec-102
    # polymorphic seam (RADD-956).
    # notify is GONE from this list (RADD-968): outbound used to mail notify's
    # watcher set, a second fan-out beside the one deciding the inbox. Users are
    # mailed by notify now, which reaches this module the other way — a deferred,
    # feature-detected call to `service.send_item_mail`.
    # workflow joined the list in RADD-982: the resolution notice fires on
    # ENTERING the done category, and the diff records the previous state by
    # NAME, so `list_states` is what turns that name back into a category.
    depends_on=(
        "projects", "auth", "items", "comments", "automations", "events",
        "attachments", "settings", "workflow",
    ),
    # RADD-961: the AI routing rule reaches `ai` DEFERRED and feature-detected —
    # the module is optional and disableable, and a missing one must fall through
    # to the next rule rather than cost a customer their email. Same edge
    # `attachments` declares for its own LLM storage rule.
    # csat is the second (RADD-982): it depends_on THIS module, so the
    # resolution notice's "yield to the survey" question can only be asked the
    # deferred way — and an uninstalled or disabled csat answering by absence
    # is exactly the right answer.
    weak_depends=("ai", "csat"),
    routers=(router, config_router, rules_router),
    # RADD-1045: the ack's plain-text body, instance-only — a service desk's
    # wording is instance policy, not per-project. Writing it goes through the
    # generic `/scoped-settings` API, gated on literal instance-admin
    # (`settings.router._authorize`) rather than `config_router`'s
    # `global.manage` — the same split every other instance-scope SettingSpec
    # already lives with (ai/ldap/csat's instance defaults, etc). `section=
    # "email"` is RADD-930's placement convention — it lands the row on
    # Settings → Email instead of the General catch-all.
    settings_keys=(
        SettingSpec(
            key="mail_ack_body",
            type="string",
            scopes=("instance",),
            label="Acknowledgement email",
            description=(
                "Plain-text body of the receipt sent when an email opens a ticket. "
                "Tokens: {{key}}, {{title}}, {{link}}, {{requester_name}} — an "
                "unrecognised token is sent verbatim. Empty sends the default wording."
            ),
            section="email",
        ),
        # RADD-982: per PROJECT as well as instance, because one installation
        # runs a service desk and a dev project, and only one of them has
        # customers to tell. ON by default — see `config.mail_send_resolved`.
        SettingSpec(
            key="mail_send_resolved",
            type="bool",
            scopes=("instance", "project"),
            label="Resolution emails",
            description=(
                "Email the ticket's external contacts when it moves into a done "
                "state (RADD-982). A project with CSAT surveys on sends the survey "
                "instead — it already announces the resolution, and one message "
                "beats two."
            ),
            section="email",
        ),
        # RADD-1048: the window the retention sweep enforces. INSTANCE-only —
        # whether customer mail is kept at rest is one installation's privacy
        # policy, and a per-project override would mean a message's fate
        # depended on which project a routing rule happened to send it to.
        SettingSpec(
            key="mail_raw_retention_days",
            type="int",
            scopes=("instance",),
            label="Raw message retention (days)",
            description=(
                "How long the original bytes of an inbound email are kept, so an "
                "over-eager quote strip or a capped attachment stays recoverable. "
                "0 keeps nothing — and lowering this reclaims what is already "
                "stored: the sweep deletes the bytes and forgets them within the "
                "hour."
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
    ui=PluginUiManifest(remote="/plugins/mailintake/remoteEntry.js", ui_api_version="1.0.0"),
)
