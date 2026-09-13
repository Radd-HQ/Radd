"""RADD-1124: one canonical external id per VCS ref, enforced by a unique index

The Forgejo webhook wrote a commit link as its bare SHA; the backfill and the
CI stamp used `commit:<owner>/<repo>:<sha>`. So a backfill after a webhook
doubled every commit and a workflow run never found the webhook's row. This:

1. rewrites bare-SHA Forgejo commit rows to the canonical shape, deriving the
   repository from the row's own URL (`https://host/<owner>/<repo>/commit/<sha>`)
   — when the canonical twin already exists on the same item, the YOUNGER of the
   pair is dropped first;
2. lowercases the repository segment of every Forgejo id (`vcs.ids` does, so an
   admin-typed `Radd-HQ/Radd` row must match what the connector writes now);
3. collapses any remaining exact duplicates, keeping the oldest row, so the
   index below cannot fail on a live database;
4. creates the partial unique index on (item_id, provider, external_id) that
   the upsert seam relies on. Manual links (external_id = '') stay outside it.

Revision ID: h1124vcsid
Revises: d1147pubkb
"""

from alembic import op

revision = "h1124vcsid"
down_revision = "d1147pubkb"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_item_vcs_links_ref"

#: A Forgejo commit row the webhook wrote before this revision, and the
#: canonical id its URL implies. `{t}` is the table alias.
_BARE = (
    "{t}.provider = 'forgejo' AND {t}.external_id ~ '^[0-9a-f]{{40}}$' "
    "AND {t}.url ~ '^https?://[^/]+/[^/]+/[^/]+/commit/'"
)
_CANONICAL = (
    "'commit:' || lower(substring({t}.url from '^https?://[^/]+/([^/]+/[^/]+)/commit/')) "
    "|| ':' || {t}.external_id"
)

#: Step 1a — a bare row whose canonical twin already exists on the same item:
#: keep the older of the two, whichever spelling it carries.
DROP_YOUNGER_TWIN = f"""
DELETE FROM item_vcs_links AS victim
USING (
    SELECT bare.id AS bare_id, bare.created_at AS bare_at,
           twin.id AS twin_id, twin.created_at AS twin_at
    FROM item_vcs_links AS bare
    JOIN item_vcs_links AS twin
      ON twin.item_id = bare.item_id
     AND twin.provider = bare.provider
     AND twin.external_id = {_CANONICAL.format(t="bare")}
    WHERE {_BARE.format(t="bare")}
) AS pair
WHERE victim.id = CASE
    WHEN (pair.bare_at, pair.bare_id) < (pair.twin_at, pair.twin_id) THEN pair.twin_id
    ELSE pair.bare_id
END
"""

#: Step 1b — the surviving bare rows take the canonical spelling.
REWRITE_BARE = (
    f"UPDATE item_vcs_links AS l SET external_id = {_CANONICAL.format(t='l')} "
    f"WHERE {_BARE.format(t='l')}"
)

#: Step 2 — the repository segment is lowercase everywhere `vcs.ids` writes.
LOWERCASE_REPO = """
UPDATE item_vcs_links
SET external_id = split_part(external_id, ':', 1) || ':'
    || lower(split_part(external_id, ':', 2)) || ':'
    || substring(external_id from '^[^:]+:[^:]+:(.*)$')
WHERE provider = 'forgejo'
  AND external_id ~ '^(commit|branch|pr):[^:]+:.+$'
  AND split_part(external_id, ':', 2) <> lower(split_part(external_id, ':', 2))
"""

#: Step 3 — exact duplicates collapse onto the oldest row.
COLLAPSE_DUPLICATES = """
DELETE FROM item_vcs_links AS younger
USING item_vcs_links AS older
WHERE older.item_id = younger.item_id
  AND older.provider = younger.provider
  AND older.external_id = younger.external_id
  AND younger.external_id <> ''
  AND (older.created_at, older.id) < (younger.created_at, younger.id)
"""


def upgrade() -> None:
    op.execute(DROP_YOUNGER_TWIN)
    op.execute(REWRITE_BARE)
    op.execute(LOWERCASE_REPO)
    op.execute(COLLAPSE_DUPLICATES)
    op.create_index(
        INDEX_NAME,
        "item_vcs_links",
        ["item_id", "provider", "external_id"],
        unique=True,
        postgresql_where="external_id <> ''",
    )


def downgrade() -> None:
    # The rewrite is not reversed: the canonical spelling is the one every
    # reader on the previous revision's backfill/CI paths already used.
    op.drop_index(INDEX_NAME, table_name="item_vcs_links")
