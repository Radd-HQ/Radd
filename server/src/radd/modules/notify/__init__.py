from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from . import dispatcher
from .kinds import NOTIFICATION_KINDS
from .router import router
from . import subscribers  # noqa: F401 — RADD-1174: the project-teardown hooks
from .types import NotifyEvent, CONSUMER_NAME

plugin = RaddPlugin(
    name="notify",
    consumer_names=(CONSUMER_NAME,),
    consumer_descriptions=((CONSUMER_NAME, "Turns events into notifications and emails"),),
    description="Notifications: the inbox, email and watching.",
    depends_on=("events", "projects", "auth", "items", "comments", "teams"),
    # RADD-1385: no edge to an optional plugin — they serve sockets
    # (NOTIFICATION_AUDIENCE, MAIL_TRANSPORT, NOTIFICATION_SUBJECT) and depend on notify.
    routers=(router,),
    # Notify's own kinds, through the registry a plugin uses (RADD-1326).
    notification_kinds=NOTIFICATION_KINDS,
    on_startup=(dispatcher.start,),
    on_shutdown=(dispatcher.stop,),
    event_types=(
        # System noise for an auditor; the ledger hides it by default.
        EventTypeSpec(
            NotifyEvent.NOTIFICATION_CREATED, "Notification created", "System",
            trigger=False, entity_type="notification", audited=False,
        ),
        # Auto-watch emits too (`auto: true`); the watcher is a subject.
        EventTypeSpec(NotifyEvent.ITEM_WATCHED, "Item watched", "Items", item_scoped=True, subjects=("item", "user")),
        EventTypeSpec(NotifyEvent.ITEM_UNWATCHED, "Item unwatched", "Items", item_scoped=True, subjects=("item", "user")),
    ),
)
