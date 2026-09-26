"""Project teardown is COMPLETE by construction (RADD-892): each owner registers a
`ProjectPurgeSpec` and the rollback iterates them. Pinned so the registry cannot
become the hardcoded list's hole again: coverage never shrinks below that list,
every table whose foreign key the DATABASE will not clear is claimed, and every
registered name is a real table with a real `project_id`.
"""

from radd.db import Base
from radd.kernel import registries

#: The list RADD-892 deleted, frozen. Registered coverage must never drop below
#: it — a silently smaller purge is a data-integrity bug, not a refactor.
_HARDCODED_PROJECT_CHILDREN = (
    "views",
    "forms",
    "releases",
    "work_items",
    "issue_types",
    "states",
    "project_timelogging",
)


def _project_fk_tables() -> dict[str, list[str | None]]:
    """table name -> the `ondelete` of every FK it has onto `projects.id`."""
    found: dict[str, list[str | None]] = {}
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            if fk.column.table.name == "projects":
                found.setdefault(table.name, []).append(fk.ondelete)
    return found


def _owning_module(table: str) -> str | None:
    """Which plugin's models.py declares this table. `Base.metadata` holds every table
        any test imported while the purge registry holds only what is LOADED, so
        comparing them without this would pass or fail by test order."""
    for mapper in Base.registry.mappers:
        local = mapper.local_table
        if local is not None and local.name == table:
            parts = mapper.class_.__module__.split(".")
            return parts[2] if parts[:2] == ["radd", "modules"] else None
    return None


def _loaded_tables(tables: dict[str, list[str | None]]) -> dict[str, list[str | None]]:
    loaded = set(registries.plugins)
    entity_tables = {spec.table for spec in registries.entities.values()}
    return {
        table: ondeletes
        for table, ondeletes in tables.items()
        if table in entity_tables or _owning_module(table) in loaded
    }


def test_registered_purge_covers_the_list_it_replaced():
    registered = set(registries.project_purge_tables())
    missing = [t for t in _HARDCODED_PROJECT_CHILDREN if t not in registered]
    assert not missing, (
        "these tables were purged with a project before RADD-892 and are no "
        f"longer claimed by any ProjectPurgeSpec: {missing}"
    )


def test_every_blocking_project_child_is_claimed():
    """A `project_id` FK with no ON DELETE action holds the project row down, so
    somebody must delete those rows first. This is the invariant that makes the
    teardown complete BY CONSTRUCTION: a new project-scoped table either cascades
    in its own migration or arrives with a purge spec, and there is no third
    option that still lets a project be deleted."""
    registered = set(registries.project_purge_tables())
    project_children = _loaded_tables(_project_fk_tables())
    # Non-vacuity: this assertion is only meaningful with the model metadata
    # fully imported, and an empty scan would pass while checking nothing.
    assert len(project_children) > 15, "model metadata is not loaded"
    unclaimed = [
        table
        for table, ondeletes in sorted(project_children.items())
        if any(action is None for action in ondeletes) and table not in registered
    ]
    assert not unclaimed, (
        "project-scoped tables the database will not clear and no plugin claims:\n  "
        + "\n  ".join(unclaimed)
        + "\nAdd a ProjectPurgeSpec to the owning plugin, or give the FK an "
        "ON DELETE action in a migration."
    )


def test_a_project_scoped_entity_registers_its_own_purge():
    """The kernel half of "complete by construction": a plugin that declares a
    project-scoped `EntitySpec` writes no model code, so it must not have to
    write teardown code either. `milestones` is the north star and the proof —
    the hardcoded list never knew its table existed."""
    from radd.kernel import entities as kentities
    from radd.modules.milestones.spec import SPEC

    kentities.register_entity(SPEC)
    assert SPEC.project_scoped and SPEC.table in registries.project_purge_tables()


def test_registered_purge_tables_are_real():
    """A typo'd table name deletes nothing and raises nothing. Read inside the test,
        never at collection: the registry is boot state, and a module-level read would
        parametrize over an empty registry and pass vacuously."""
    tables = registries.project_purge_tables()
    assert tables, "no ProjectPurgeSpec registered at all — the registry is empty"
    for table in tables:
        assert table in Base.metadata.tables, f"{table!r} is not a mapped table"
        assert "project_id" in Base.metadata.tables[table].columns, (
            f"{table!r} has no project_id column — the purge deletes by project_id"
        )
