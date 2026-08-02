"""Retention policy (spec 99 §4) — pure, so it needs no disk and no Postgres.

The rule this guards: retention prunes a schedule's OWN scheduled artifacts and
nothing else. Deleting somebody's explicit backup to satisfy a rotation policy is
not a rotation policy, and leaving a schedule with zero backups is not retention.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from radd.backup.store import StoredBackup, prunable
from radd.backup.types import BackupKind

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
MINE = "11111111-1111-1111-1111-111111111111"
THEIRS = "22222222-2222-2222-2222-222222222222"


class _Manifest:
    """Only the three fields the policy reads."""

    def __init__(self, kind: str, schedule_id: str | None):
        self.kind = kind
        self.schedule_id = schedule_id


class _Backup(StoredBackup):
    """A StoredBackup with a fixed `created_at` (the real one stats the file)."""

    def __init__(self, name, *, age_days, kind, schedule_id, complete=True):
        super().__init__(
            name=name,
            path=Path(f"/nowhere/{name}"),
            size_bytes=1024,
            manifest=_Manifest(kind, schedule_id),  # type: ignore[arg-type]
            complete=complete,
        )
        self._created = NOW - timedelta(days=age_days)

    @property
    def created_at(self) -> datetime:
        return self._created


def _scheduled(name, age_days, *, schedule_id=MINE, complete=True):
    return _Backup(
        name, age_days=age_days, kind=BackupKind.SCHEDULED.value,
        schedule_id=schedule_id, complete=complete,
    )


def _names(result):
    return {item.name for item in result}


def _prune(backups, **kwargs):
    kwargs.setdefault("schedule_id", MINE)
    kwargs.setdefault("keep_last", None)
    kwargs.setdefault("keep_days", None)
    return prunable(backups, now=NOW, **kwargs)


def test_keep_last_prunes_the_oldest_beyond_the_limit():
    backups = [_scheduled(f"b{i}", age_days=i) for i in range(5)]
    assert _names(_prune(backups, keep_last=3)) == {"b3", "b4"}


def test_keep_days_prunes_by_age():
    backups = [_scheduled(f"b{i}", age_days=i * 10) for i in range(4)]  # 0, 10, 20, 30 days
    assert _names(_prune(backups, keep_days=15)) == {"b2", "b3"}


def test_the_newest_healthy_backup_is_never_pruned():
    """Even an absurd policy leaves the schedule with something."""
    backups = [_scheduled("old", age_days=400), _scheduled("newest", age_days=399)]
    assert _names(_prune(backups, keep_last=1, keep_days=1)) == {"old"}


def test_a_single_backup_is_never_pruned():
    assert _prune([_scheduled("only", age_days=9999)], keep_days=1) == []


@pytest.mark.parametrize(
    "kind", [BackupKind.MANUAL, BackupKind.UPLOADED, BackupKind.PRE_RESTORE]
)
def test_deliberate_backups_are_never_auto_pruned(kind):
    """Manual, uploaded and pre-restore artifacts were created by an act of
    intent; a rotation policy does not get to delete them."""
    deliberate = _Backup("kept", age_days=999, kind=kind.value, schedule_id=MINE)
    backups = [_scheduled("fresh", age_days=0), deliberate]
    assert _names(_prune(backups, keep_last=1, keep_days=1)) == set()


def test_another_schedules_backups_are_untouched():
    mine = [_scheduled(f"mine{i}", age_days=i) for i in range(4)]
    theirs = [_scheduled(f"theirs{i}", age_days=i, schedule_id=THEIRS) for i in range(4)]
    assert _names(_prune(mine + theirs, keep_last=1)) == {"mine1", "mine2", "mine3"}


def test_incomplete_artifacts_are_pruned_regardless_of_count():
    """A footerless file is a crashed dump, not a backup — it must not occupy a
    retention slot, and it must not be the thing kept as 'the newest'."""
    backups = [
        _scheduled("crashed", age_days=0, complete=False),
        _scheduled("good", age_days=1),
    ]
    assert _names(_prune(backups, keep_last=5)) == {"crashed"}


def test_no_policy_prunes_nothing():
    backups = [_scheduled(f"b{i}", age_days=i) for i in range(10)]
    assert _prune(backups) == []


def test_schema_changelog_is_complete():
    """A bump without a reason is noise — every version must explain itself."""
    from radd.schema_version import SCHEMA_CHANGELOG, SCHEMA_VERSION

    assert set(SCHEMA_CHANGELOG) == set(range(1, SCHEMA_VERSION + 1))
    assert all(SCHEMA_CHANGELOG[v].strip() for v in SCHEMA_CHANGELOG)


def test_compatibility_refuses_a_newer_schema():
    """A backup from a future Radd holds data this build cannot read."""
    from radd.backup.service import compatibility
    from radd.schema_version import SCHEMA_VERSION

    class _M:
        schema_version = SCHEMA_VERSION + 1

    verdict = compatibility(_M())  # type: ignore[arg-type]
    assert not verdict.restorable and not verdict.needs_override
    assert "newer Radd" in (verdict.reason or "")


def test_compatibility_accepts_the_current_schema():
    from radd.backup.service import compatibility
    from radd.schema_version import SCHEMA_VERSION

    class _M:
        schema_version = SCHEMA_VERSION

    assert compatibility(_M()).restorable  # type: ignore[arg-type]


def test_compatibility_refuses_an_unreadable_manifest():
    from radd.backup.service import compatibility

    assert not compatibility(None).restorable
