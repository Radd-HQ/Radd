from radd.kernel import CapabilitySpec, EventTypeSpec, PluginUiManifest
from radd.kernel import RaddPlugin

from . import dispatcher, registry
from .config_router import router as config_router
from .router import router
from .types import MailEvent

plugin = RaddPlugin(
    name="mailintake",
    core=False,  # optional plugin — disableable via the plugin manager
    description="Email-to-issue intake (spec 47) + the requester loop (spec 62): an "
    "IMAP poller turning unseen messages into items (or reply comments on a keyed "
    "subject) as the system actor, mail_contacts for external requesters, ack "
    "emails, and an outbound consumer mailing public comments back to the contact.",
    # attachments: mail parts become item attachments through the spec-102
    # polymorphic seam (RADD-956).
    # attachments: mail parts become item attachments (RADD-956).
    # notify: watchers ARE the participant set, so outbound reuses that fan-out
    # rather than growing a second recipient model that would drift (RADD-955).
    depends_on=(
        "projects", "auth", "items", "comments", "automations", "events",
        "attachments", "notify",
    ),
    # RADD-961: the AI routing rule reaches `ai` DEFERRED and feature-detected —
    # the module is optional and disableable, and a missing one must fall through
    # to the next rule rather than cost a customer their email. Same edge
    # `attachments` declares for its own LLM storage rule.
    weak_depends=("ai",),
    routers=(router, config_router),
    # Seed rows from env BEFORE the poller starts, or the first tick finds
    # no sources on a fresh instance (RADD-958).
    on_startup=(registry.seed_from_env, dispatcher.start),
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
            subjects=("item",),
        ),
        EventTypeSpec(MailEvent.DROPPED, "Email discarded", "Email"),
    ),
    # Federated UI (spec 94): the external-requester chip in the issue rail
    # (web/remotes/mailintake), rendered by the host via the issue.panel.section slot.
    ui=PluginUiManifest(remote="/plugins/mailintake/remoteEntry.js", ui_api_version="1.0.0"),
)
