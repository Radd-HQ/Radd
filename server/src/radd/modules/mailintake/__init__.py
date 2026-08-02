from radd.config import settings
from radd.kernel import CapabilitySpec, PluginUiManifest
from radd.kernel import RaddPlugin

from . import dispatcher
from .router import router

plugin = RaddPlugin(
    name="mailintake",
    core=False,  # optional plugin — disableable via the plugin manager
    description="Email-to-issue intake (spec 47) + the requester loop (spec 62): an "
    "IMAP poller turning unseen messages into items (or reply comments on a keyed "
    "subject) as the system actor, mail_contacts for external requesters, ack "
    "emails, and an outbound consumer mailing public comments back to the contact.",
    depends_on=("projects", "auth", "items", "comments", "automations", "events"),
    routers=(router,),
    on_startup=(dispatcher.start,),
    on_shutdown=(dispatcher.stop,),
    capabilities=(
        CapabilitySpec(
            "email_intake",
            "Email-to-issue intake",
            "connector",
            check=lambda: {"enabled": bool(settings.mail_imap_host)},
        ),
    ),
    # Federated UI (spec 94): the external-requester chip in the issue rail
    # (web/remotes/mailintake), rendered by the host via the issue.panel.section slot.
    ui=PluginUiManifest(remote="/plugins/mailintake/remoteEntry.js", ui_api_version="1.0.0"),
)
