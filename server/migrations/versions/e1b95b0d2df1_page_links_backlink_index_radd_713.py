"""page_links backlink index (RADD-713)

Revision ID: e1b95b0d2df1
Revises: d702slug
Create Date: 2026-08-02 23:17:10.563008

Hand-trimmed. Autogenerate additionally proposed dropping `item_embeddings` and
`page_embeddings` (spec 103 manages those OUTSIDE Base.metadata on purpose, so
they always look like drift), dropping `acme_notes` (an example plugin's table,
present only when that plugin is installed), and renaming a batch of indexes and
constraints left over from the RADD-701 docs->pages rename. None of that belongs
to this change, and the embeddings drops would have destroyed a populated index.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1b95b0d2df1'
down_revision = 'd702slug'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'page_links',
        sa.Column('source_page_id', sa.Uuid(), nullable=False),
        sa.Column('target_page_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ['source_page_id'], ['pages.id'],
            name=op.f('fk_page_links_source_page_id_pages'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['target_page_id'], ['pages.id'],
            name=op.f('fk_page_links_target_page_id_pages'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('source_page_id', 'target_page_id', name=op.f('pk_page_links')),
    )
    op.create_index(
        op.f('ix_page_links_target_page_id'), 'page_links', ['target_page_id'], unique=False,
    )
    _backfill()


def _backfill() -> None:
    """Index the pages that already exist.

    Without this the table only fills as pages happen to be re-saved, so an
    established wiki would show empty backlinks on every page — the feature
    would look broken rather than new. The parser is imported rather than
    reimplemented in SQL: two copies of "what counts as a link" would drift, and
    this one is already tested.
    """
    from radd.modules.pages.backlinks import _targets  # noqa: PLC0415

    bind = op.get_bind()
    pages = bind.execute(
        sa.text(
            "SELECT p.id, p.body, p.slug, s.slug AS space_slug"
            " FROM pages p JOIN page_spaces s ON s.id = p.space_id"
        )
    ).fetchall()
    by_slug = {(row.space_slug, row.slug): row.id for row in pages}
    known_ids = {row.id for row in pages}

    rows: list[dict[str, object]] = []
    for page in pages:
        slugs, ids = _targets(page.body or "")
        targets = {by_slug[key] for key in slugs if key in by_slug}
        targets |= {i for i in ids if i in known_ids}
        targets.discard(page.id)
        rows.extend({"s": page.id, "t": target} for target in targets)

    if rows:
        bind.execute(
            sa.text(
                "INSERT INTO page_links (source_page_id, target_page_id)"
                " VALUES (:s, :t) ON CONFLICT DO NOTHING"
            ),
            rows,
        )


def downgrade() -> None:
    op.drop_index(op.f('ix_page_links_target_page_id'), table_name='page_links')
    op.drop_table('page_links')
