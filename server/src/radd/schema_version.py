"""The instance's data-compatibility version (spec 99 §2).

An alembic revision is an exact identity with no ordering and no severity — a
build can ask "do I know this one?" but not "is it safe?". This is the second
number, deliberately almost never incremented:

    SCHEMA_VERSION increments when restoring older data can no longer be made
    correct by running `alembic upgrade head` alone.

Adding a table, a nullable column or an index: no bump. Dropping a column that
held data, collapsing two entities, changing what existing rows mean: bump, with
a changelog line saying what a restore of older data loses.

`tests/test_backup.py` asserts every version from 1 to SCHEMA_VERSION has an
entry, so a bump without a reason fails the suite.
"""

SCHEMA_VERSION = 1

SCHEMA_CHANGELOG: dict[int, str] = {
    1: "Baseline — specs 01-99.",
}
