"""spec 119: automation_validations — what a validate trigger governs

Revision ID: d119valbind
Revises: 6fac157b10ac
Create Date: 2026-08-12

The index behind intake validation. One row per (automation, validate-trigger
node, target), rebuilt from the graph on every write exactly as
`automation_triggers` is — the graph stays the source of truth, and this is what
lets a submit answer "is anything validating this" in one query instead of
parsing every stored graph on the request path.

`target_id` carries no foreign key on purpose: the target is polymorphic across
forms, issue types and projects, and a column cannot reference three tables. A
deleted target leaves a row that matches nothing, which is the intended
degradation — a stale binding, not a broken graph.
"""
from alembic import op
import sqlalchemy as sa


revision = "d119valbind"
down_revision = "6fac157b10ac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_validations",
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("target_kind", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["automation_id"],
            ["automations.id"],
            name=op.f("fk_automation_validations_automation_id_automations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "automation_id",
            "node_id",
            "target_kind",
            "target_id",
            name=op.f("pk_automation_validations"),
        ),
    )
    op.create_index(
        op.f("ix_automation_validations_target_kind"),
        "automation_validations",
        ["target_kind"],
    )
    op.create_index(
        op.f("ix_automation_validations_target_id"),
        "automation_validations",
        ["target_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_automation_validations_target_id"), table_name="automation_validations")
    op.drop_index(
        op.f("ix_automation_validations_target_kind"), table_name="automation_validations"
    )
    op.drop_table("automation_validations")
