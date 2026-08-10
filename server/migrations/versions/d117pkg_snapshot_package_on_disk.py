"""Spec 117 — a downloaded snapshot's bytes move from the object store to disk.

Attachments went through the spec-102 blob API and out to the object store. That
is the right home for a page's attachments and the wrong one for a DOWNLOAD: one
real section pushed 49 GB through Garage's S3 API to cache bytes that might never
be imported, and the download crawled. They now live in a plain directory per
snapshot, so `file_path` (relative to the package) replaces the blob pointers.

Existing rows lose their pointer, which is deliberate rather than migrated: the
blob names cannot become paths without copying tens of gigabytes between two
stores to preserve a CACHE. Re-download instead — that is what a cache is for.
Any orphaned blobs are the object store's own GC problem.

Revision ID: d117pkg
Revises: c117confluence
"""

import sqlalchemy as sa
from alembic import op

revision = "d117pkg"
down_revision = "c117confluence"
branch_labels = None
depends_on = None

TABLE = "confluence_snapshot_attachments"


def upgrade() -> None:
    op.add_column(
        TABLE, sa.Column("file_path", sa.String(1000), nullable=False, server_default="")
    )
    op.drop_column(TABLE, "storage_name")
    op.drop_column(TABLE, "storage_host_id")


def downgrade() -> None:
    op.add_column(
        TABLE, sa.Column("storage_name", sa.String(500), nullable=False, server_default="")
    )
    op.add_column(TABLE, sa.Column("storage_host_id", sa.Uuid(), nullable=True))
    op.drop_column(TABLE, "file_path")
