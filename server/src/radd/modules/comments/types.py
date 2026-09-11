from enum import StrEnum

# Max characters of the comment body included in event payloads (webhook-friendly).
EXCERPT_MAX_CHARS = 200


class CommentParentType(StrEnum):
    """What a comment hangs off (RADD-717). A WIRE FORMAT — it is stored in the
    `comments.entity_type` column and appears in event payloads — so a member
    here is renamed by migration, not by editing."""

    ITEM = "item"
    PAGE = "page"


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


class CommentSlice(StrEnum):
    ALL = "all"
    DISCUSSION = "discussion"
    INLINE = "inline"
