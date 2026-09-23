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
    #: RADD-1283: a project's who-may-resolve-a-thread rules changed.
    RESOLUTION_POLICY_UPDATED = "comment.resolution_policy_updated"


class CommentEntity(StrEnum):
    COMMENT = "comment"
    RESOLUTION_POLICY = "thread_resolution_policy"


class ThreadResolvers(StrEnum):
    """Who may resolve or unresolve a thread (RADD-1283). A WIRE FORMAT, stored in
    `thread_resolution_rules.resolvers`. Managers (the parent's manage
    permission) may always resolve, whatever the rule — except that `managers`
    is exactly that and nothing more."""

    AUTHOR = "author"  # the thread's author, plus managers — the default
    ASSIGNEE = "assignee"  # the author and the issue's assignee, plus managers
    ANYONE = "anyone"  # anyone who may comment on the parent
    MANAGERS = "managers"  # managers only


#: What applies where no rule does: the rule RADD-1282 shipped with.
DEFAULT_THREAD_RESOLVERS = ThreadResolvers.AUTHOR


class ResolveReach(StrEnum):
    """What one reader may resolve on one parent: every thread, only the ones
    they started, or none. Computed once per parent, applied per thread."""

    ANY = "any"
    OWN = "own"
    NONE = "none"


class CommentSlice(StrEnum):
    ALL = "all"
    DISCUSSION = "discussion"
    INLINE = "inline"
