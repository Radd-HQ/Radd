"""The builtin routing-rule types (spec 102): ask the uploader, and CIDR.

Every handler answers a host id or None (fall through) — a rule can only
NARROW where an upload goes, never error an upload out. Other types arrive on
the STORAGE_ROUTING_RULE socket: the `llm` classifier is the `ai` plugin's
(RADD-1387), which is why this module no longer imports `ai` at all.
"""

import ipaddress
import logging
import uuid
from collections.abc import Collection

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .context import RoutingContext

logger = logging.getLogger(__name__)


# --- user choice ---------------------------------------------------------------


class UserChoiceConfig(BaseModel):
    """No knobs: the offered set is every host flagged user_selectable."""


class UserChoiceRule:
    config_model = UserChoiceConfig

    async def evaluate(
        self, session: AsyncSession, ctx: RoutingContext, config: UserChoiceConfig
    ) -> uuid.UUID | None:
        """The user's pick, honored only if it names a selectable host — so
        API/SDK/importer uploads (which never prompt) sail through, and a stale
        or forged choice cannot reach a non-selectable host."""
        if ctx.chosen_host_id is None:
            return None
        from ..models import StorageHost

        host = await session.get(StorageHost, ctx.chosen_host_id)
        if host is None or not host.user_selectable:
            return None
        return host.id


# --- CIDR ----------------------------------------------------------------------


class CidrRange(BaseModel):
    cidr: str
    host_id: uuid.UUID


class CidrConfig(BaseModel):
    ranges: list[CidrRange] = Field(min_length=1)


def match_cidr(source_ip: str | None, ranges: list[CidrRange]) -> uuid.UUID | None:
    """First range containing the address (pure). Unparseable input -> None."""
    if not source_ip:
        return None
    try:
        address = ipaddress.ip_address(source_ip)
    except ValueError:
        return None
    for entry in ranges:
        try:
            if address in ipaddress.ip_network(entry.cidr, strict=False):
                return entry.host_id
        except ValueError:
            logger.warning("storage cidr rule: invalid range %r skipped", entry.cidr)
    return None


class CidrRule:
    config_model = CidrConfig

    async def evaluate(
        self, session: AsyncSession, ctx: RoutingContext, config: CidrConfig
    ) -> uuid.UUID | None:
        return match_cidr(ctx.source_ip, config.ranges)

    async def captured_types(
        self,
        session: AsyncSession,
        config: CidrConfig,
        *,
        source_ip: str | None,
        content_types: Collection[str],
    ) -> set[str]:
        """A range matching the caller's network decides EVERYTHING they
        upload — the network, not the file, picks the host."""
        return set(content_types) if match_cidr(source_ip, config.ranges) is not None else set()
