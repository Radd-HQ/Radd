from radd.kernel import RaddPlugin

from .router import router

async def _startup() -> None:
    from . import cascade

    await cascade.start()


async def _shutdown() -> None:
    from . import cascade

    await cascade.stop()


plugin = RaddPlugin(
    on_startup=(_startup,),
    on_shutdown=(_shutdown,),
    name="events",
    consumer_names=("events.cascade",),
    depends_on=(),
    weak_depends=("auth",),
    description="The event log every other feature reads from — history, notifications, webhooks and automations.",
    routers=(router,),
)
