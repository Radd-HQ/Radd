from radd.kernel import EventTypeSpec, PermissionSpec, RaddPlugin, SlqFieldSpec

from .automation import COMMENT_GATE, COMMENT_TOKENS  # RADD-1322/1324: "Comment is" + {{comment.*}}
from .slq import commented_by_item_ids

from .router import router
from .mcptools import MCP_TOOLS  # RADD-1477: update_comment / delete_comment
from . import subscribers  # noqa: F401 — RADD-1174: the project-teardown hooks
from .types import CommentEntity, CommentEvent

from radd.kernel.registry import register_relation, register_relation_domain
from radd.kernel.specs import RelationSpec
from .models import Comment

# RADD-816 (Q4): what @own MEANS for a comment — the author column. Both forms
# mandatory (the RADD-823 contract); registered on the manifest so the loader's
# clear() cannot drop it.
COMMENT_OWN = RelationSpec(
    resource="comment",
    key="own",
    label="they authored",
    where=lambda actor: Comment.author_id == actor.user_id,
    holds=lambda actor, row: row.author_id == actor.user_id,
)
register_relation(COMMENT_OWN)

# RADD-844: `comment.write` is CREATE-shaped — there is no comment row yet, so
# its relation qualifier names a relation to the parent ITEM. The declaration
# is what makes `comment.write@participant` ("comment on issues shared with
# them") validate in a role editor and resolve at the item gate, instead of
# being read against the comment's own @own (the author) and refused.
register_relation_domain("comment.write", "item")

#: The comment's OWN payload data (the `item`/`page` refs are the kernel's).
_COMMENT_PAYLOAD_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "entity_type": {"type": "string", "enum": ["item", "page"]},
        "entity_id": {"type": "string"},
        "parent_comment_id": {
            "type": ["string", "null"],
            "description": "The thread root's id when this comment is a REPLY; null for a root.",
        },
        "visibility": {"type": "string", "enum": ["public", "internal"]},
        "excerpt": {"type": "string"},
        "visible_to_teams": {"type": "array", "items": {"type": "string"}},
    },
}


plugin = RaddPlugin(
    name="comments",
    record_local_entities=(CommentEntity.COMMENT.value,),  # RADD-1328
    automation_nodes=(COMMENT_GATE,),
    token_providers=(COMMENT_TOKENS,),
    permissions=(
        PermissionSpec("comment.write", "project", "Comment on the project's work items."),
        PermissionSpec("comment.read_internal", "project", "See internal (team-only) comments."),
        PermissionSpec(
            "comment.delete",
            "project",
            "Delete other people's comments.",
            implied_by=("project.manage",),
        ),
    ),
    relations=(COMMENT_OWN,),
    relation_domains=(("comment.write", "item"),),
    description="Comments and threaded discussions on issues and pages.",
    # itemtypes: RADD-1283's resolution rules are scoped by issue type.
    depends_on=("items", "auth", "projects", "events", "teams", "itemtypes"),
    # `commented_by = me` on the ITEM dialect — see slq.py.
    slq_fields=(
        SlqFieldSpec(name="commented_by", label="Commented by", item_ids=commented_by_item_ids),
    ),
    # Deferred import: `gc` -> `service`/`parents` -> `items.service`, and items
    # imports back this way round.
    cascades=lambda: __import__(
        "radd.modules.comments.gc", fromlist=["cascades"]
    ).cascades(),
    routers=(router,),
    mcp_tools=MCP_TOOLS,

    event_types=(
        # RADD-1248: `page` is a declared subject — a comment on a page carries
        # the page ref (None on an item comment) and the engine runs such an
        # event on the itemless path instead of dropping it as "item vanished".
        EventTypeSpec(
            CommentEvent.CREATED, "Comment added", "Comments", item_scoped=True,
            subjects=("page",), payload_schema=_COMMENT_PAYLOAD_SCHEMA,
        ),
        EventTypeSpec(
            CommentEvent.UPDATED, "Comment edited", "Comments", item_scoped=True, has_changes=True,
            subjects=("page",), payload_schema=_COMMENT_PAYLOAD_SCHEMA,
        ),
        EventTypeSpec(
            CommentEvent.DELETED, "Comment deleted", "Comments", item_scoped=True,
            subjects=("page",), payload_schema=_COMMENT_PAYLOAD_SCHEMA,
        ),
        # RADD-1283: configuration, audited — not an automation trigger.
        EventTypeSpec(
            CommentEvent.RESOLUTION_POLICY_UPDATED, "Thread resolution rules changed", "Admin",
            has_changes=True, trigger=False, subjects=("project",),
        ),
    ),
)
