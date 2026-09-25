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


class CommentOrigin(StrEnum):
    """WHERE a comment came from when no person typed it (RADD-1318). NULL is a
    person — the app, the API, MCP. Set by the SERVER only, never by a request
    body: a client that could claim `inbound_mail` could stop its own comment
    reaching the customer.

    It replaced "the author is the SYSTEM user" as the test for "not a real
    reply", which was wrong both ways: an automation's comment is SYSTEM-authored
    yet meant for the customer (the relay dropped it), and the same comment with
    `act_as` is a person's yet is still not a human answer (the SLA counted it).
    """

    #: Mail NO account stands behind — the requester's own words, filed by
    #: intake under the system user. A recognised person's mailed reply is that
    #: person's comment (NULL), exactly as if they had typed it: an agent who
    #: answers by email is relayed and counts as a response.
    INBOUND_MAIL = "inbound_mail"
    PORTAL = "portal"  # a requester writing through the portal
    AUTOMATION = "automation"  # written while an automation ran (derived)
    IMPORT = "import"  # carried over by an importer


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
