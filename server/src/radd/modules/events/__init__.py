from radd.kernel import RaddPlugin

from .router import router

async def _startup() -> None:
    from . import cascade

    await cascade.start()


async def _shutdown() -> None:
    from . import cascade

    await cascade.stop()


plugin = RaddPlugin(
    on_startup=_startup,
    on_shutdown=_shutdown,
    name="events",
    description="Transactional outbox: append-only event log, the spine every consumer reads.",
    routers=(router,),
)
