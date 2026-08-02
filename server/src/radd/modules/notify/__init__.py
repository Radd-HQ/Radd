from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from . import dispatcher
from .router import router
from .types import NotifyEvent

plugin = RaddPlugin(
    name="notify",
    description="Notifications + watchers: an outbox consumer fanning item/comment "
    "events into per-user in-app notifications and email digests.",
    depends_on=("events", "projects", "auth", "items", "comments"),
    routers=(router,),
    on_startup=(dispatcher.start,),
    on_shutdown=(dispatcher.stop,),
    event_types=(
        EventTypeSpec(NotifyEvent.ITEM_WATCHED, "Item watched", "Items", item_scoped=True),
        EventTypeSpec(NotifyEvent.ITEM_UNWATCHED, "Item unwatched", "Items", item_scoped=True),
    ),
)
