"""Merge coverage oracle: every place a user id is stored must be handled.

A merge moves the survivor's id into every place the old id was used. The failure
mode is silent — a column nobody added to `_MERGE_REPOINT` keeps pointing at a
row that no longer exists (or, on a CASCADE column, is simply deleted along with
it), and nothing errors. That is how `global_role_grants` and `team_managers`
came to be dropped on every merge: both are CASCADE, both were missed, and the
symptom was only "my permissions vanished".

So this walks the MAPPER METADATA rather than trusting the lists, and fails when
a user-bearing column is not covered. A new module that stores a user id has to
say what a merge should do with it.
"""

import pytest
from sqlalchemy import inspect

from radd.config import settings
from radd.db import Base
from radd.kernel import import_models
from radd.modules.auth.models import User
from radd.modules.auth.service import _MERGE_DEDUPE, _MERGE_PURGE, _MERGE_REPOINT

#: Columns that hold a user id but are deliberately NOT repointed, with the reason.
#: Adding to this list is a decision; leaving a column out of it is a bug.
_EXEMPT: dict[str, str] = {
    # Handled generically for every resource type by `_repoint_user_access_grants`,
    # which also has to rewrite subject_type — a plain UPDATE cannot express it.
    "access_grants.subject_id": "repointed by _repoint_user_access_grants",
    # The user IS the row; merging destroys the source's copy (_MERGE_PURGE) and
    # the target keeps its own identity-private credentials/preferences.
    "users.id": "the primary key of the row being merged away",
    # RADD-836 U1: an admin previewing the merged-away account should NOT be
    # silently repointed at the survivor — the FK's SET NULL ends the preview
    # and the deps fallback hands the admin themselves back.
    "sessions.view_as_user_id": "ondelete SET NULL deliberately ends the preview",
}

#: Non-FK columns that still hold user ids (no constraint to find them by).
_NAME_HINTS = (
    "user_id", "actor_id", "author_id", "owner_id", "created_by", "updated_by",
    "added_by", "assignee_id", "reporter_id", "requested_by", "created_by_id",
)


def _covered() -> set[str]:
    covered = {f"{table}.{column}" for table, column in _MERGE_REPOINT}
    covered |= {f"{table}.{column}" for table, _entities, column in _MERGE_DEDUPE}
    covered |= {f"{table}.user_id" for table in _MERGE_PURGE}
    return covered


def _user_bearing_columns() -> dict[str, str]:
    """{'table.column': why we think it holds a user id} across every model."""
    import_models(settings.modules)
    found: dict[str, str] = {}
    for table in Base.metadata.tables.values():
        for column in table.columns:
            key = f"{table.name}.{column.name}"
            if any(fk.column.table.name == "users" for fk in column.foreign_keys):
                found[key] = "foreign key to users.id"
            elif column.name in _NAME_HINTS and str(column.type).upper().startswith("UUID"):
                found[key] = "named like a user reference"
    return found


def test_every_user_bearing_column_is_handled_by_merge():
    uncovered = {
        key: why
        for key, why in _user_bearing_columns().items()
        if key not in _covered() and key not in _EXEMPT
    }
    assert not uncovered, (
        "These columns store a user id but no merge rule covers them, so a merge "
        "would strand or destroy them:\n"
        + "\n".join(f"  {key}  ({why})" for key, why in sorted(uncovered.items()))
        + "\n\nAdd each to _MERGE_REPOINT (plain attribution), _MERGE_DEDUPE "
        "(unique per user — collisions dropped), or _EXEMPT with a reason."
    )


def test_the_merge_lists_only_name_real_columns():
    """The reverse check: a rename or a dropped table would leave a rule firing
    UPDATE against something that no longer exists — an error at merge time, on
    someone's live instance, rather than here."""
    import_models(settings.modules)
    tables = Base.metadata.tables
    problems: list[str] = []
    for table, column in _MERGE_REPOINT:
        if table not in tables:
            problems.append(f"_MERGE_REPOINT names missing table {table}")
        elif column not in tables[table].columns:
            problems.append(f"_MERGE_REPOINT names missing column {table}.{column}")
    for table, entity_cols, user_col in _MERGE_DEDUPE:
        if table not in tables:
            problems.append(f"_MERGE_DEDUPE names missing table {table}")
            continue
        for column in (*entity_cols, user_col):
            if column not in tables[table].columns:
                problems.append(f"_MERGE_DEDUPE names missing column {table}.{column}")
    for table in _MERGE_PURGE:
        if table not in tables:
            problems.append(f"_MERGE_PURGE names missing table {table}")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    "table,entity_cols",
    [(t, e) for t, e, _c in _MERGE_DEDUPE],
)
def test_dedupe_entity_columns_match_a_real_uniqueness_rule(table, entity_cols):
    """A dedupe rule exists to avoid violating a unique index. If the entity
    columns don't correspond to one, either the rule is wrong or the constraint
    was dropped — both silently turn a merge into an IntegrityError."""
    import_models(settings.modules)
    mapped = Base.metadata.tables[table]
    user_col = next(c for t, _e, c in _MERGE_DEDUPE if t == table)
    wanted = {*entity_cols, user_col}
    uniques = [set(mapped.primary_key.columns.keys())]
    uniques += [
        set(constraint.columns.keys())
        for constraint in mapped.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    ]
    uniques += [set(index.columns.keys()) for index in mapped.indexes if index.unique]
    assert any(wanted == unique for unique in uniques), (
        f"{table}: dedupe on {sorted(wanted)} matches no unique key "
        f"(found {[sorted(u) for u in uniques]})"
    )


def test_users_table_is_reachable():
    """Guards the oracle itself: if the model set failed to import, every check
    above would pass vacuously."""
    import_models(settings.modules)
    assert "users" in Base.metadata.tables
    assert inspect(User).mapped_table.name == "users"
    assert len(_user_bearing_columns()) > 25
