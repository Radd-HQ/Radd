from .types import CONSUMER_NAME, WebhookEvent
from radd.kernel import EntityLinkSpec
from radd.kernel import EventTypeSpec, RaddPlugin
from radd.kernel import CrudResourceSpec, PermissionSpec

from . import dispatcher
from .router import router

plugin = RaddPlugin(
    name="webhooks",
    entity_links=(
        EntityLinkSpec('webhook_endpoint', ('/settings/webhooks',)),
    ),
    consumer_names=(CONSUMER_NAME,),
    consumer_descriptions=((CONSUMER_NAME, "Delivers webhook calls"),),
    permissions=(
        PermissionSpec(
            "webhook.manage",
            "global",
            "Manage endpoints that export instance event payloads to external services.",
            implied_by=("global.manage",),
        ),
    ),
    crud_resources=(CrudResourceSpec("webhook", "global", "webhooks", "webhook.manage"),),
    description="Webhooks: signed event deliveries to your own endpoints, with retries.",
    depends_on=("projects", "events", "auth", "fields", "items"),
    routers=(router,),
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
