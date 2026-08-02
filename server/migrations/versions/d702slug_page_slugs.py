"""RADD-702: pages get a slug, so a page has a readable, stable URL.

`/pages/<space>/<page>` replaces `/docs/<uuid>/<uuid>`. The slug is unique PER
SPACE (two spaces may each hold a `getting-started`), derived from the title,
and then FROZEN — renaming a page must not break links that already exist.

Backfill mirrors `core.page_slugify` + `core.unique_slug` exactly, including the
`page` fallback for a title that slugifies to nothing and the `-2`, `-3` suffix
for collisions. It runs in Python rather than SQL because those two rules have
to stay in one place; a clever window function here would be a second
implementation to keep in step.

Revision ID: d702slug
Revises: d701pages
"""

import re

from alembic import op
import sqlalchemy as sa

revision = "d702slug"
down_revision = "d701pages"
branch_labels = None
depends_on = None

_SEPARATOR = re.compile(r"[^a-z0-9]+")
_MAX = 120


def _slugify(title: str) -> str:
    slug = _SEPARATOR.sub("-", (title or "").lower()).strip("-")
    return slug[:_MAX] or "page"


def upgrade() -> None:
    op.add_column("pages", sa.Column("slug", sa.String(length=120), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, space_id, title FROM pages ORDER BY space_id, created_at, id")
    ).fetchall()
    taken: dict[str, set[str]] = {}
    for page_id, space_id, title in rows:
        space_taken = taken.setdefault(str(space_id), set())
        candidate = _slugify(title)
        slug = candidate
        suffix = 2
        while slug in space_taken:
            slug = f"{candidate}-{suffix}"
            suffix += 1
        space_taken.add(slug)
        bind.execute(
            sa.text("UPDATE pages SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": page_id},
        )

    op.alter_column("pages", "slug", nullable=False)
    op.create_unique_constraint("uq_pages_space_slug", "pages", ["space_id", "slug"])


def downgrade() -> None:
    op.drop_constraint("uq_pages_space_slug", "pages", type_="unique")
    op.drop_column("pages", "slug")
