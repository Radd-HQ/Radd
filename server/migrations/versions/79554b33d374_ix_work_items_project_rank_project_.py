"""ix_work_items_project_rank: project-scoped rank scans

Revision ID: 79554b33d374
Revises: fd68d1c4d8fd
Create Date: 2026-07-31 23:29:21.179545

"""
from alembic import op
import sqlalchemy as sa


revision = '79554b33d374'
down_revision = 'fd68d1c4d8fd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_work_items_project_rank", "work_items", ["project_id", "rank"]
    )


def downgrade() -> None:
    op.drop_index("ix_work_items_project_rank", table_name="work_items")
