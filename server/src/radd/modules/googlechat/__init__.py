from radd.config import settings
from .types import CONSUMER_NAME
from radd.kernel import CapabilitySpec
from radd.kernel import RaddPlugin

from . import dispatcher

plugin = RaddPlugin(
    name="googlechat",
    consumer_names=(CONSUMER_NAME,),
    core=False,  # optional plugin — disableable via the plugin manager
    description="Google Chat notifier (spec 47): an outbox consumer posting compact "
    "messages for selected events to an incoming webhook URL. Fire-and-forget.",
    depends_on=("events", "projects", "auth"),
    on_startup=(dispatcher.start,),
    on_shutdown=(dispatcher.stop,),
    capabilities=(
        CapabilitySpec(
            "google_chat",
            "Google Chat notifier",
            "connector",
            check=lambda: {"enabled": bool(settings.googlechat_webhook_url)},
        ),
    ),
)
