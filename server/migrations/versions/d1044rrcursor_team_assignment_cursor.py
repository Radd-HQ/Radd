"""RADD-1044 — round-robin assignment cursor, one row per team.

The `assign_round_robin` automation action distributes new work across a team's
members in a stable order, skipping inactive and away accounts. The rotation
position is engine state, kept apart from user data (like
automation_schedule_state): ONE row per TEAM so two rules over the same team
share the rotation rather than each restarting it and piling work on the first
member.

`last_assigned_user_id` is nullable and SET NULL on user delete — a departed
cursor-holder just means the next pick starts from the top of the rotation. The
team key CASCADEs: the rotation is meaningless once the team is gone.

Revision ID: d1044rrcursor
Revises: d1043slatype
"""

import sqlalchemy as sa
from alembic import op

revision = "d1044rrcursor"
down_revision = "d1043slatype"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "team_assignment_cursors",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("last_assigned_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_team_assignment_cursors_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_assigned_user_id"],
            ["users.id"],
            name=op.f("fk_team_assignment_cursors_last_assigned_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("team_id", name=op.f("pk_team_assignment_cursors")),
    )


def downgrade() -> None:
    op.drop_table("team_assignment_cursors")
