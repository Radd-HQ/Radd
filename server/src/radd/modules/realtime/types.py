"""Wire constants for the realtime module."""

# WebSocket close code for a failed handshake auth (4000-range = application-defined).
WS_CLOSE_UNAUTHENTICATED = 4401

# Entity string whose events are private to their recipient (notify module's
# NotifyEntity.NOTIFICATION — mirrored here as a wire constant so realtime
# doesn't import notify; keep in sync).
NOTIFICATION_ENTITY = "notification"
