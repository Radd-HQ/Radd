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
    # RADD-1385: no edge to any optional plugin. What notify used to import from
    # them — participants' team audience, mailintake's transport, the wiki's
    # watchers/read gate/space picker — arrives on kernel sockets
    # (NOTIFICATION_AUDIENCE, MAIL_TRANSPORT, NOTIFICATION_SUBJECT), which a
    # runtime disable withdraws. A `try: import` never could: plugin code is
    # always importable. Those plugins depend on notify now, not the reverse.
    routers=(router,),
    # RADD-1326: notify's own kinds through the same registry a plugin uses —
    # the preferences matrix and the inbox read the registry, not this module.
    notification_kinds=NOTIFICATION_KINDS,
    on_startup=(dispatcher.start,),
    on_shutdown=(dispatcher.stop,),
    event_types=(
        # RADD-1168: emitted since spec 26 and never registered. System noise
        # for an auditor; the ledger (RADD-1169) hides it by default.
        EventTypeSpec(
            NotifyEvent.NOTIFICATION_CREATED, "Notification created", "System",
            trigger=False, entity_type="notification", audited=False,
        ),
        # RADD-1320: auto-watch emits too (`auto: true`); the watcher is a subject.
        EventTypeSpec(NotifyEvent.ITEM_WATCHED, "Item watched", "Items", item_scoped=True, subjects=("item", "user")),
        EventTypeSpec(NotifyEvent.ITEM_UNWATCHED, "Item unwatched", "Items", item_scoped=True, subjects=("item", "user")),
    ),
)
