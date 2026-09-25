"""Durable environment initialization for independently installed connectors."""

from sqlalchemy.dialects.postgresql import insert
from .models import VcsSeed


async def claim_seed(session, provider: str) -> bool:
    return (
        await session.scalar(
            insert(VcsSeed)
            .values(provider=provider)
            .on_conflict_do_nothing()
            .returning(VcsSeed.provider)
        )
        is not None
    )


async def require_distinct_secret(session, model, connection):
    """One shared receiver must be able to identify exactly one active host."""
    from sqlalchemy import select
    from radd.exceptions import ConflictError

    if not connection.active or not connection.webhook_secret:
        return
    with session.no_autoflush:
        query = select(model.id).where(
            model.active, model.webhook_secret == connection.webhook_secret
        )
        if connection.id is not None:
            query = query.where(model.id != connection.id)
        if await session.scalar(query) is not None:
            raise ConflictError(
                "connection", reason="Use a different webhook secret for each active host"
            )
