"""Building an inbound profile from a cached snapshot (spec 100).

The accumulator is pure; this is the thin async shell that streams the cache
through it and folds in the instance-wide catalogs Jira gave us at download time.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import JiraSnapshot
from ..snapshot import store
from ..types import SnapshotCatalog
from .accumulate import ProfileAccumulator, merge_catalog
from .types import InboundProfile, PersonEntry, VocabEntry

__all__ = [
    "InboundProfile",
    "PersonEntry",
    "ProfileAccumulator",
    "VocabEntry",
    "build",
]


async def build(session: AsyncSession, snapshot: JiraSnapshot) -> InboundProfile:
    """Profile every cached issue, then add the vocabularies the project has
    configured but never used.

    The order matters: counts come from the SNAPSHOT (what the project actually
    does), the long tail comes from the CATALOG (what the instance allows). A
    catalog value with no snapshot use lands with count 0, which is what puts it
    in the hidden-and-ignored band instead of on screen.
    """
    accumulator = ProfileAccumulator(store.catalog(snapshot, SnapshotCatalog.FIELDS))
    async for row in store.iter_issues(session, snapshot.id):
        accumulator.add(row.payload)
    profile = accumulator.profile()

    profile.issue_types = merge_catalog(
        profile.issue_types, store.catalog(snapshot, SnapshotCatalog.ISSUE_TYPES)
    )
    profile.statuses = merge_catalog(
        profile.statuses, store.catalog(snapshot, SnapshotCatalog.STATUSES)
    )
    profile.priorities = merge_catalog(
        profile.priorities, store.catalog(snapshot, SnapshotCatalog.PRIORITIES)
    )
    profile.resolutions = merge_catalog(
        profile.resolutions, store.catalog(snapshot, SnapshotCatalog.RESOLUTIONS)
    )
    profile.link_types = merge_catalog(
        profile.link_types, store.catalog(snapshot, SnapshotCatalog.LINK_TYPES)
    )
    profile.versions = merge_catalog(
        profile.versions, store.catalog(snapshot, SnapshotCatalog.VERSIONS)
    )
    profile.components = merge_catalog(
        profile.components, store.catalog(snapshot, SnapshotCatalog.COMPONENTS)
    )
    return profile
