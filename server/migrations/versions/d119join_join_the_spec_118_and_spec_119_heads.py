"""join the spec-118 and spec-119 heads

The two waves were built in parallel worktrees: spec 118 (scoped notification
rules, d118notifrules -> d118notifchan) and spec 119 (intake validation,
d119valbind). Each chain is independent -- different tables, no ordering
constraint between them -- so this merge point carries no operations; it only
gives the graph a single head again.

Revision ID: d119join
Revises: d118notifchan, d119valbind
Create Date: 2026-08-12 13:12:33.272592

"""
from alembic import op
import sqlalchemy as sa


revision = 'd119join'
down_revision = ('d118notifchan', 'd119valbind')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
