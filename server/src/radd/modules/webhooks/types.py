from enum import StrEnum


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    DEAD = "dead"  # retry schedule exhausted; manual replay later


class WebhookEvent(StrEnum):
    ENDPOINT_CREATED = "webhook_endpoint.created"
    ENDPOINT_UPDATED = "webhook_endpoint.updated"
    ENDPOINT_DELETED = "webhook_endpoint.deleted"  # spec 87 — takes the delivery log with it


class WebhookEntity(StrEnum):
    ENDPOINT = "webhook_endpoint"
    DELIVERY = "webhook_delivery"  # RADD-1096: named in replay's refusals


# Standard Webhooks (https://www.standardwebhooks.com/): whsec_ + base64 key,
# HMAC-SHA256 over "{msg_id}.{timestamp}.{body}", "v1,<base64>" signature header.
SECRET_PREFIX = "whsec_"
SIGNATURE_VERSION = "v1"

# This module's cursor name in the events stream.
CONSUMER_NAME = "webhooks.dispatcher"
