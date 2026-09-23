"""RADD-1290: Milestones is off by default — except where someone already uses it.

The example plugin now declares `enabled_by_default=False`, so an instance with
no stored state for it stops loading it. An instance that has created milestones
was using the feature; it gets an explicit ENABLED row so the upgrade takes
nothing away. Existing rows (enabled or disabled) are left as they are.

Revision ID: d1290milestonesoff
Revises: d1285releaseflow
"""
import sqlalchemy as sa
from alembic import op

revision = "d1290milestonesoff"
down_revision = "d1285releaseflow"
branch_labels = None
depends_on = None

PLUGIN_ID = "radd.milestones"


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("milestones"):
        return
    if bind.execute(sa.text("SELECT 1 FROM installed_plugins WHERE id = :i"), {"i": PLUGIN_ID}).scalar():
        return
    if not bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM milestones)")).scalar():
        return
    bind.execute(sa.text(
        "INSERT INTO installed_plugins (id, version, state, config) VALUES (:i, '1.0.0', 'enabled', '{}')"
    ), {"i": PLUGIN_ID})


def downgrade() -> None:
    pass
