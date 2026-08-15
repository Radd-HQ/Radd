from .types import CONSUMER_NAME
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec, PermissionSpec

from . import dispatcher
from .router import router

plugin = RaddPlugin(
    name="webhooks",
    consumer_names=(CONSUMER_NAME,),
    permissions=(
        PermissionSpec(
            "webhook.manage",
            "global",
            "Manage webhook endpoints (global).",
            implied_by=("global.manage",),
        ),
    ),
    crud_resources=(CrudResourceSpec("webhook", "global", "webhooks", "webhook.manage"),),
    description="Standard-Webhooks dispatcher: signed deliveries with retries, fed by the outbox.",
    depends_on=("projects", "events", "auth", "fields", "items"),
    routers=(router,),
    on_startup=(dispatcher.reencrypt_secrets, dispatcher.start),
    on_shutdown=(dispatcher.stop,),
)
