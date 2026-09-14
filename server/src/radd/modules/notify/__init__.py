from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from . import dispatcher
from .router import router
from . import subscribers  # noqa: F401 — RADD-1174: the project-teardown hooks
from .types import NotifyEvent, CONSUMER_NAME

plugin = RaddPlugin(
    name="notify",
    consumer_names=(CONSUMER_NAME,),
    description="Notifications + watchers: an outbox consumer fanning item/comment "
    "events into per-user in-app notifications, a per-event mailer, and email digests.",
    depends_on=("events", "projects", "auth", "items", "comments", "teams"),
    # participants: the recipient union (spec 72), resolved at fan-out time.
    # mailintake: the mail TRANSPORT (RADD-968) — `service.send_item_mail`,
    # reached deferred + feature-detected so a disabled/absent mail plugin
    # degrades to the env relay rather than silencing notification email.
    # pages: spec 118 — space subscriptions need a space's NAME to display and a
    # page's read gate to enforce. Same shape as the two above: pages loads
    # AFTER notify and is a disableable plugin, so both reaches are deferred and
    # feature-detected, and an instance with the wiki off degrades rather than
    # failing to import.
    weak_depends=("participants", "mailintake", "pages"),
    routers=(router,),
    on_startup=(dispatcher.start,),
    on_shutdown=(dispatcher.stop,),
    event_types=(
        # RADD-1168: emitted since spec 26 and never registered. System noise
        # for an auditor; the ledger (RADD-1169) hides it by default.
        EventTypeSpec(
            NotifyEvent.NOTIFICATION_CREATED, "Notification created", "System",
            trigger=False, entity_type="notification", audited=False,
        ),
        EventTypeSpec(NotifyEvent.ITEM_WATCHED, "Item watched", "Items", item_scoped=True),
        EventTypeSpec(NotifyEvent.ITEM_UNWATCHED, "Item unwatched", "Items", item_scoped=True),
    ),
)
