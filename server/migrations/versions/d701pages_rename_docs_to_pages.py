"""RADD-701: the docs subsystem becomes Pages, internals included.

Tables, permission atoms, event history, attachment parents and the embeddings
cache all carry the old vocabulary. Renaming only the visible strings would have
left three names in the codebase — which is how the subsystem ended up called
"docs", "wiki" and "knowledge base" in the first place.

Everything here is a RENAME, never a drop-and-recreate: no page, version, link,
grant or embedding is lost.

Two rewrites are not optional:

* **Stored role JSONB** holds raw atom strings, and `RoleRead.permissions` is a
  `list[Permission]` — a `doc.read` left in a saved role would 500 `GET /roles`
  the moment anyone opened the roles matrix (the spec-87 precedent, which
  learned this the hard way when atoms were dropped).
* **Access grants** address resources by `resource_type`; a stale `doc_page`
  there would silently detach every per-page grant.

Event rows are rewritten too. An event's `event_type`/`entity_type` name the
thing that happened, and the thing has been renamed — leaving history on the old
names would show "unknown event" rows in the audit trail forever.

Every step is conditional on the table/column existing, so this also applies
cleanly to an instance that never enabled the module (no pages, no embeddings).

Revision ID: d701pages
Revises: d111ci
"""

from alembic import op
import sqlalchemy as sa

revision = "d701pages"
down_revision = "d111ci"
branch_labels = None
depends_on = None


TABLES = [
    ("doc_spaces", "page_spaces"),
    ("doc_pages", "pages"),
    ("doc_page_versions", "page_versions"),
    ("item_doc_links", "item_page_links"),
]

ATOMS = [
    ("doc.read", "page.read"),
    ("doc.write", "page.write"),
    ("doc.manage", "page.manage"),
    ("doc.delete", "page.delete"),
]

# Leading fragments — `doc_page.created` -> `page.created`.
EVENT_PREFIXES = [
    ("doc_space.", "page_space."),
    ("doc_page.", "page."),
    ("doc_link.", "page_link."),
]

# Whole values — entity/resource type columns.
ENTITY_TYPES = [
    ("doc_space", "page_space"),
    ("doc_page", "page"),
    ("doc_link", "page_link"),
]


def _exec(statement: str, params: dict | None = None) -> None:
    """`op.execute` takes no bind parameters; parameterised DML goes to the bind."""
    op.get_bind().execute(sa.text(statement), params or {})


def _table_exists(name: str) -> bool:
    return op.get_bind().scalar(sa.text("SELECT to_regclass(:n)"), {"n": name}) is not None


def _column_exists(table: str, column: str) -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        )
    )


def _rename_tables(pairs: list[tuple[str, str]]) -> None:
    for old, new in pairs:
        if _table_exists(old) and not _table_exists(new):
            _exec(f'ALTER TABLE "{old}" RENAME TO "{new}"')


def _rewrite_values(pairs: list[tuple[str, str]], table: str, column: str) -> None:
    """Whole-value swap on a text column."""
    if not _table_exists(table) or not _column_exists(table, column):
        return
    for old, new in pairs:
        _exec(
            f"UPDATE {table} SET {column} = :new WHERE {column} = :old",
            {"new": new, "old": old},
        )


def _rewrite_prefixes(pairs: list[tuple[str, str]], table: str, column: str) -> None:
    """Leading-fragment swap on a text column (event type namespaces)."""
    if not _table_exists(table) or not _column_exists(table, column):
        return
    for old, new in pairs:
        _exec(
            f"UPDATE {table} SET {column} = :new || substring({column} from :cut) "
            f"WHERE {column} LIKE :like",
            {"new": new, "cut": len(old) + 1, "like": f"{old}%"},
        )


def _rewrite_json_strings(pairs: list[tuple[str, str]], table: str, column: str) -> None:
    """Swap quoted string values inside a JSONB document (role permission arrays,
    key scopes, webhook event-type lists). Exact because every value here is a
    full atom/event name, never a substring of another one."""
    if not _table_exists(table) or not _column_exists(table, column):
        return
    for old, new in pairs:
        _exec(
            f"UPDATE {table} SET {column} = replace({column}::text, :old_q, :new_q)::jsonb "
            f"WHERE {column}::text LIKE :like",
            {"old_q": f'"{old}"', "new_q": f'"{new}"', "like": f'%"{old}"%'},
        )


def _apply(atoms, event_prefixes, entities) -> None:
    _rewrite_json_strings(atoms, "roles", "permissions")
    _rewrite_json_strings(atoms, "api_tokens", "scopes")
    _rewrite_prefixes(event_prefixes, "events", "event_type")
    _rewrite_values(entities, "events", "entity_type")
    _rewrite_values(entities, "attachments", "entity_type")
    _rewrite_values(entities, "access_grants", "resource_type")
    _rewrite_values(entities, "notifications", "entity_type")
    # webhooks.event_types is a JSONB array of event names; a prefix swap there
    # is a quoted-string swap over the document.
    for old, new in event_prefixes:
        _rewrite_json_strings(
            [(f"{old}{suffix}", f"{new}{suffix}") for suffix in EVENT_SUFFIXES],
            "webhooks",
            "event_types",
        )


# The suffixes the pages module actually emits (types.PageEvent) — enumerated so
# the webhook JSON swap can target whole values rather than a fragment.
EVENT_SUFFIXES = ["created", "updated", "deleted", "moved", "restored"]


def upgrade() -> None:
    _rename_tables(TABLES)

    # The pgvector cache (spec 103) is runtime-managed outside Base.metadata;
    # renaming keeps every embedding rather than forcing a full re-embed.
    if _table_exists("doc_embeddings") and not _table_exists("page_embeddings"):
        _exec("ALTER TABLE doc_embeddings RENAME TO page_embeddings")
        _exec("ALTER INDEX IF EXISTS ix_doc_embeddings_model RENAME TO ix_page_embeddings_model")
        _exec("ALTER INDEX IF EXISTS ix_doc_embeddings_hnsw RENAME TO ix_page_embeddings_hnsw")

    _apply(ATOMS, EVENT_PREFIXES, ENTITY_TYPES)


def downgrade() -> None:
    _rename_tables([(new, old) for old, new in TABLES])
    if _table_exists("page_embeddings") and not _table_exists("doc_embeddings"):
        _exec("ALTER TABLE page_embeddings RENAME TO doc_embeddings")
        _exec("ALTER INDEX IF EXISTS ix_page_embeddings_model RENAME TO ix_doc_embeddings_model")
        _exec("ALTER INDEX IF EXISTS ix_page_embeddings_hnsw RENAME TO ix_doc_embeddings_hnsw")
    _apply(
        [(new, old) for old, new in ATOMS],
        [(new, old) for old, new in EVENT_PREFIXES],
        [(new, old) for old, new in ENTITY_TYPES],
    )
