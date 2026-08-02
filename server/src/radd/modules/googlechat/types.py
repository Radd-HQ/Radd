"""Wire constants for the Google Chat outbound notifier (spec 47)."""

# This module's cursor name in the events stream.
CONSUMER_NAME = "googlechat.notifier"

# Wire strings for the event types the default RADD_GOOGLECHAT_EVENT_TYPES selects.
# Constants, not imports — this notifier must not depend on items/slas/docs being
# enabled (same precedent as notify.types.SLA_BREACHED_EVENT).
ITEM_CREATED_EVENT = "item.created"  # ItemEvent.CREATED
SLA_BREACHED_EVENT = "sla.breached"  # SlaEvent.BREACHED
PAGE_CREATED_EVENT = "page.created"  # pages module (spec 43)

# Events read per consumer iteration (the poll interval is a config setting).
BATCH_SIZE = 100

# Seconds allowed for one incoming-webhook POST. Fire-and-forget: a failed
# delivery is logged and the offset advances (spec 47 — no retry queue).
REQUEST_TIMEOUT = 5.0
