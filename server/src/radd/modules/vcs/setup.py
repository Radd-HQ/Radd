"""Durable environment initialization for independently installed connectors."""

import hmac

from sqlalchemy.dialects.postgresql import insert

from radd import secretbox

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
    """One shared receiver must be able to identify exactly one active host.
    Secrets are ciphertext under a fresh nonce each (RADD-1446), so equality is
    decided here on the decrypted values, never by the database."""
    from sqlalchemy import select
    from radd.exceptions import ConflictError

    if not connection.active or not connection.webhook_secret:
        return
    secret = secretbox.decrypt(connection.webhook_secret)
    with session.no_autoflush:
        query = select(model.webhook_secret).where(model.active, model.webhook_secret != "")
        if connection.id is not None:
            query = query.where(model.id != connection.id)
        others = (await session.execute(query)).scalars()
        if any(hmac.compare_digest(secretbox.decrypt(other), secret) for other in others):
            raise ConflictError(
                "connection", reason="Use a different webhook secret for each active host"
            )
