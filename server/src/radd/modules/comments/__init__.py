from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin, SlqFieldSpec

from .slq import commented_by_item_ids

from .router import router
from .types import CommentEvent

plugin = RaddPlugin(
    name="comments",
    description="Comments on work items: CRUD + comment.* events; counts feed item hydration.",
    depends_on=("items", "auth", "projects", "events", "teams"),
    # `commented_by = me` on the ITEM dialect — see slq.py.
    slq_fields=(
        SlqFieldSpec(name="commented_by", label="Commented by", item_ids=commented_by_item_ids),
    ),
    routers=(router,),
    event_types=(
        EventTypeSpec(CommentEvent.CREATED, "Comment added", "Comments", item_scoped=True),
        EventTypeSpec(CommentEvent.UPDATED, "Comment edited", "Comments", item_scoped=True),
        EventTypeSpec(CommentEvent.DELETED, "Comment deleted", "Comments", item_scoped=True),
    ),
)
