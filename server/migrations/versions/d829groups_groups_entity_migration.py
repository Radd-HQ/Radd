"""Groups become their own entity; teams stop pretending to be directory
objects (RADD-829).

Behaviour-preserving by construction: every directory-linked team becomes an
ordinary team CONTAINING the one group it was linked to — same people, same
access, different shape. Directory-source member rows move to the group (the
group carries the membership); manual rows survive as user rows; directory
rows on teams that were somehow unlinked survive as user rows too (crude on
purpose — losing nobody beats modelling a state that should not exist).

`team_members` is rebuilt with a surrogate PK and a user-XOR-group subject,
WITHOUT `source` (`MemberSource` retires — a user row is by definition manual
now). `TeamSource`, the teams directory columns and the six directory
TeamChange event values retire with no reader-side alias (no-backcompat).

Revision ID: d829groups
Revises: aff6111e24f7
"""

import sqlalchemy as sa
from alembic import op

revision = "d829groups"
down_revision = "aff6111e24f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dn", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("directory_missing_since", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
        sa.UniqueConstraint("dn", name="uq_groups_dn"),
    )
    op.create_table(
        "group_parents",
        sa.Column("child_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["child_id"], ["groups.id"], name=op.f("fk_group_parents_child_id_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["groups.id"], name=op.f("fk_group_parents_parent_id_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("child_id", "parent_id", name=op.f("pk_group_parents")),
    )
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name=op.f("fk_group_members_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_group_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("group_id", "user_id", name=op.f("pk_group_members")),
    )

    # One group per linked team (DNs are unique instance-wide; two teams linked
    # to the same group collapse into one group row).
    op.execute(
        """
        INSERT INTO groups (id, dn, name)
        SELECT DISTINCT ON (directory_group_dn)
               gen_random_uuid(), directory_group_dn,
               COALESCE(directory_group_name, name)
        FROM teams WHERE directory_group_dn IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE groups g SET directory_missing_since = t.directory_missing_since
        FROM teams t
        WHERE t.directory_group_dn = g.dn AND t.directory_missing_since IS NOT NULL
        """
    )
    # Directory-source memberships move to the group.
    op.execute(
        """
        INSERT INTO group_members (group_id, user_id)
        SELECT DISTINCT g.id, tm.user_id
        FROM team_members tm
        JOIN teams t ON t.id = tm.team_id
        JOIN groups g ON g.dn = t.directory_group_dn
        WHERE tm.source = 'directory'
        """
    )

    # Rebuild team_members: stage the surviving USER rows, drop the old table
    # (its constraint names are the ones the new table must carry), recreate,
    # refill. Manual rows survive as user rows; so do directory rows on
    # UNLINKED teams (no group to carry them — losing nobody beats modelling a
    # state that should not exist).
    op.execute(
        """
        CREATE TABLE _tm_829_scratch AS
        SELECT tm.team_id, tm.user_id
        FROM team_members tm
        JOIN teams t ON t.id = tm.team_id
        WHERE tm.source != 'directory' OR t.directory_group_dn IS NULL
        """
    )
    op.drop_table("team_members")
    op.create_table(
        "team_members",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(user_id IS NULL) != (group_id IS NULL)", name="ck_team_members_one_subject"
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name=op.f("fk_team_members_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_team_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name=op.f("fk_team_members_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_members")),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_members_user"),
        sa.UniqueConstraint("team_id", "group_id", name="uq_team_members_group"),
    )
    op.execute(
        "INSERT INTO team_members (team_id, user_id) SELECT team_id, user_id FROM _tm_829_scratch"
    )
    # The linked team now CONTAINS its group.
    op.execute(
        """
        INSERT INTO team_members (team_id, group_id)
        SELECT t.id, g.id FROM teams t JOIN groups g ON g.dn = t.directory_group_dn
        """
    )
    op.execute("DROP TABLE _tm_829_scratch")
    op.create_index(op.f("ix_team_members_team_id"), "team_members", ["team_id"])
    op.create_index(op.f("ix_team_members_user_id"), "team_members", ["user_id"])
    op.create_index(op.f("ix_team_members_group_id"), "team_members", ["group_id"])

    # The teams directory columns retire with TeamSource.
    for column in ("directory_group_dn", "directory_group_name", "directory_missing_since", "source"):
        op.execute(f"ALTER TABLE teams DROP COLUMN IF EXISTS {column}")


def downgrade() -> None:
    raise RuntimeError(
        "RADD-829 is not reversible: MemberSource/TeamSource were destroyed "
        "(no-backcompat rule) — restore from a backup instead"
    )
