from enum import StrEnum

# Max characters of the comment body included in event payloads (webhook-friendly).
EXCERPT_MAX_CHARS = 200


class CommentVisibility(StrEnum):
    """Spec 07: internal comments are gated by Permission.COMMENT_READ_INTERNAL."""

    PUBLIC = "public"
    INTERNAL = "internal"


class CommentEvent(StrEnum):
    CREATED = "comment.created"
    UPDATED = "comment.updated"
    DELETED = "comment.deleted"


class CommentEntity(StrEnum):
    COMMENT = "comment"
