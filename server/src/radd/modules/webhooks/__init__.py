from .types import CONSUMER_NAME, WebhookEvent
from radd.kernel import EventTypeSpec, RaddPlugin
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
    # RADD-1168: emitted since spec 25 and never registered. Not triggers.
    event_types=(
        EventTypeSpec(
            WebhookEvent.ENDPOINT_CREATED, "Webhook endpoint created", "Admin",
            trigger=False, entity_type="webhook_endpoint",
        ),
        EventTypeSpec(
            WebhookEvent.ENDPOINT_UPDATED, "Webhook endpoint updated", "Admin",
            has_changes=True, trigger=False, entity_type="webhook_endpoint",
        ),
        EventTypeSpec(
            WebhookEvent.ENDPOINT_DELETED, "Webhook endpoint deleted", "Admin",
            trigger=False, entity_type="webhook_endpoint",
        ),
    ),
    on_startup=(dispatcher.reencrypt_secrets, dispatcher.start),
    on_shutdown=(dispatcher.stop,),
)
