"""Authorization answers reused across requests, while nothing has changed (RADD-1560).

Every request resolved the same things from scratch before doing its own work:
which groups and teams the person is in, which grants reach them, what each
role holds. Eight statements on the cheapest request, the same answers as the
request before it.

**The epoch.** One row, `auth_epoch`. Database triggers on the tables those
answers are read from (`global_role_grants`, `roles`, `team_members`,
`group_members`, `group_parents`) add one to it, in the transaction that makes
the change — whatever made it: the service layer, a bulk statement, a foreign
key cascade from a deleted team, someone at a psql prompt. A cached answer is
tagged with the epoch it was read at and is used only while the epoch is still
that number. So there is no time window: a revoked grant is gone from the next
request on every process, because that request reads a different epoch.

**What can still go wrong, and why it does not.**
- *A transaction that changed authorization data reads its own change.* Its
  epoch is not committed, so it neither uses the cache nor fills it
  (`current` answers None for it): an uncommitted view must never be filed
  under a number another transaction may later commit.
- *A change this module has no trigger on.* Then the cache is wrong until the
  next change. That is why the watched tables are listed in ONE place
  (`WATCHED_TABLES`, checked against the migration by a test) and why the
  answers cached here are only ever read from those tables.
- *A grant that expires.* Expiry is a comparison with the clock, not a change
  to a row, so cached grant rows carry `expires_at` and are filtered when read.

`RADD_AUTH_CACHE=false` turns it off; every caller then asks the database, as
before.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from radd.config import settings

#: The tables whose rows the cached answers are derived from. Each has a
#: statement trigger that bumps the epoch (migration `d1560authepoch`).
WATCHED_TABLES = ("global_role_grants", "roles", "team_members", "group_members", "group_parents")

#: The epoch, and whether THIS transaction wrote it (an uncommitted bump).
_EPOCH = text(
    "SELECT value, xmin::text = pg_current_xact_id_if_assigned()::text FROM auth_epoch WHERE id = 1"
)
_MEMO = "radd.auth_epoch"
_UNREAD = object()

_entries: OrderedDict[tuple[str, Hashable], tuple[int, Any]] = OrderedDict()


async def current(session: AsyncSession) -> int | None:
    """The epoch to read and file answers under, or None when this transaction
    must not use the cache (it is off, or the transaction changed authorization
    data itself). Read once per request; forgotten when the session writes."""
    if not settings.auth_cache:
        return None
    memo = session.info.get(_MEMO, _UNREAD)
    if memo is not _UNREAD:
        return memo
    row = (await session.execute(_EPOCH)).one_or_none()
    value = None if row is None or row[1] else int(row[0])
    session.info[_MEMO] = value
    return value


async def cached[T](
    session: AsyncSession, namespace: str, key: Hashable, load: Callable[[], Awaitable[T]]
) -> T:
    """`load()`, or what it returned last time if no watched table has changed
    since. The value must be immutable: it is shared between requests."""
    epoch = await current(session)
    if epoch is None:
        return await load()
    slot = (namespace, key)
    hit = _entries.get(slot)
    if hit is not None and hit[0] == epoch:
        _entries.move_to_end(slot)
        return hit[1]
    value = await load()
    _entries[slot] = (epoch, value)
    _entries.move_to_end(slot)
    while len(_entries) > settings.auth_cache_max_entries:
        _entries.popitem(last=False)
    return value


def clear() -> None:
    """Drop everything (tests; a process that wants a clean slate)."""
    _entries.clear()


# A session that has WRITTEN anything re-reads the epoch before trusting it
# again: the write may have been to a watched table, directly or by cascade,
# and then this transaction's own view is ahead of every committed epoch.


@event.listens_for(Session, "after_flush")
def _forget_on_flush(session: Session, _context: object) -> None:
    session.info.pop(_MEMO, None)


@event.listens_for(Session, "do_orm_execute")
def _forget_on_write(state: Any) -> None:
    if not state.is_select:
        state.session.info.pop(_MEMO, None)
