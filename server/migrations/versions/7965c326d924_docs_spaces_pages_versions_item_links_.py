"""docs: spaces, pages, versions, item links (spec 43)

Wiki tables (doc_spaces / doc_pages / doc_page_versions / item_doc_links),
the FTS expression GIN index over page titles+bodies, and the builtin-role
backfill (viewer += doc.read, member += doc.write) so stored role rows keep
mirroring the seeded definitions (the immutability contract, as spec 36 did).

Revision ID: 7965c326d924
Revises: 313d9671a1d3

"""
from alembic import op
import sqlalchemy as sa


revision = '7965c326d924'
down_revision = '313d9671a1d3'
branch_labels = None
depends_on = None

_ROLE_ADDS = (("viewer", "doc.read"), ("member", "doc.write"))


def upgrade() -> None:
    op.create_table(
        'doc_spaces',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('position', sa.Float(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['workspace_id'], ['workspaces.id'],
            name=op.f('fk_doc_spaces_workspace_id_workspaces'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_doc_spaces')),
        sa.UniqueConstraint('workspace_id', 'slug', name=op.f('uq_doc_spaces_workspace_id_slug')),
    )
    op.create_index(
        op.f('ix_doc_spaces_workspace_id'), 'doc_spaces', ['workspace_id'], unique=False
    )

    op.create_table(
        'doc_pages',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('space_id', sa.Uuid(), nullable=False),
        sa.Column('parent_id', sa.Uuid(), nullable=True),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('position', sa.Float(), server_default='0', nullable=False),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('updated_by', sa.Uuid(), nullable=False),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['space_id'], ['doc_spaces.id'],
            name=op.f('fk_doc_pages_space_id_doc_spaces'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['parent_id'], ['doc_pages.id'],
            name=op.f('fk_doc_pages_parent_id_doc_pages'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['created_by'], ['users.id'], name=op.f('fk_doc_pages_created_by_users')
        ),
        sa.ForeignKeyConstraint(
            ['updated_by'], ['users.id'], name=op.f('fk_doc_pages_updated_by_users')
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_doc_pages')),
    )
    op.create_index('ix_doc_pages_space_parent', 'doc_pages', ['space_id', 'parent_id'])
    # Live FTS (spec 43): the search endpoint queries this exact expression —
    # no outbox indexer, the corpus is written only through the docs module.
    op.create_index(
        'ix_doc_pages_fts',
        'doc_pages',
        [sa.text("to_tsvector('english', title || ' ' || body)")],
        postgresql_using='gin',
    )

    op.create_table(
        'doc_page_versions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('page_id', sa.Uuid(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('author_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['page_id'], ['doc_pages.id'],
            name=op.f('fk_doc_page_versions_page_id_doc_pages'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['author_id'], ['users.id'], name=op.f('fk_doc_page_versions_author_id_users')
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_doc_page_versions')),
        sa.UniqueConstraint('page_id', 'version', name=op.f('uq_doc_page_versions_page_id_version')),
    )
    op.create_index(op.f('ix_doc_page_versions_page_id'), 'doc_page_versions', ['page_id'])

    op.create_table(
        'item_doc_links',
        sa.Column('item_id', sa.Uuid(), nullable=False),
        sa.Column('page_id', sa.Uuid(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['item_id'], ['work_items.id'],
            name=op.f('fk_item_doc_links_item_id_work_items'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['page_id'], ['doc_pages.id'],
            name=op.f('fk_item_doc_links_page_id_doc_pages'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['created_by'], ['users.id'], name=op.f('fk_item_doc_links_created_by_users')
        ),
        sa.PrimaryKeyConstraint('item_id', 'page_id', name=op.f('pk_item_doc_links')),
    )
    op.create_index(op.f('ix_item_doc_links_page_id'), 'item_doc_links', ['page_id'])

    # Builtin role rows mirror the seeded definitions exactly (immutable) —
    # append the spec-43 doc permissions where absent, as spec 36's backfill did.
    for key, value in _ROLE_ADDS:
        op.execute(
            f"""
            UPDATE roles
            SET permissions = permissions || '["{value}"]'::jsonb
            WHERE is_builtin AND key = '{key}'
              AND NOT permissions @> '["{value}"]'::jsonb
            """
        )


def downgrade() -> None:
    for key, value in _ROLE_ADDS:
        op.execute(
            f"""
            UPDATE roles
            SET permissions = permissions - '{value}'
            WHERE is_builtin AND key = '{key}'
            """
        )
    op.drop_index(op.f('ix_item_doc_links_page_id'), table_name='item_doc_links')
    op.drop_table('item_doc_links')
    op.drop_index(op.f('ix_doc_page_versions_page_id'), table_name='doc_page_versions')
    op.drop_table('doc_page_versions')
    op.drop_index('ix_doc_pages_fts', table_name='doc_pages', postgresql_using='gin')
    op.drop_index('ix_doc_pages_space_parent', table_name='doc_pages')
    op.drop_table('doc_pages')
    op.drop_index(op.f('ix_doc_spaces_workspace_id'), table_name='doc_spaces')
    op.drop_table('doc_spaces')
