"""states + labels: workflow states as data, item labels; migrate category -> state_id

Revision ID: 0002
Revises: cf3aa0d3ef02

Hand-written: existing projects get the default state set seeded and existing
items are mapped from their category to the matching default state.
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "cf3aa0d3ef02"
branch_labels = None
depends_on = None

# Frozen snapshot of radd.modules.workflow.types.DEFAULT_STATES at this revision —
# migrations must not import app code.
DEFAULT_STATES = (
    ("Triage", "triage", True),
    ("Backlog", "backlog", False),
    ("Todo", "todo", False),
    ("In Progress", "in_progress", False),
    ("Code Review", "in_progress", False),
    ("Done", "done", False),
    ("Canceled", "canceled", False),
)
CATEGORY_TO_STATE = {
    "triage": "Triage",
    "backlog": "Backlog",
    "todo": "Todo",
    "in_progress": "In Progress",
    "done": "Done",
    "canceled": "Canceled",
}


def upgrade() -> None:
    op.create_table(
        "states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_states_project_id_projects")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_states")),
        sa.UniqueConstraint("project_id", "name", name=op.f("uq_states_project_id_name")),
    )
    op.create_index(op.f("ix_states_project_id"), "states", ["project_id"], unique=False)

    op.create_table(
        "labels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_labels_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_labels")),
        sa.UniqueConstraint("workspace_id", "name", name=op.f("uq_labels_workspace_id_name")),
    )
    op.create_index(op.f("ix_labels_workspace_id"), "labels", ["workspace_id"], unique=False)

    op.create_table(
        "item_labels",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("label_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["work_items.id"],
            name=op.f("fk_item_labels_item_id_work_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["label_id"],
            ["labels.id"],
            name=op.f("fk_item_labels_label_id_labels"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", "label_id", name=op.f("pk_item_labels")),
    )

    op.add_column("work_items", sa.Column("state_id", sa.Uuid(), nullable=True))

    conn = op.get_bind()
    project_ids = conn.execute(sa.text("SELECT id FROM projects")).scalars().all()
    for project_id in project_ids:
        state_ids: dict[str, uuid.UUID] = {}
        for position, (name, category, is_default) in enumerate(DEFAULT_STATES, start=1):
            state_id = uuid.uuid4()
            state_ids[name] = state_id
            conn.execute(
                sa.text(
                    "INSERT INTO states (id, project_id, name, category, position, is_default)"
                    " VALUES (:id, :project_id, :name, :category, :position, :is_default)"
                ),
                {
                    "id": state_id,
                    "project_id": project_id,
                    "name": name,
                    "category": category,
                    "position": position,
                    "is_default": is_default,
                },
            )
        for category, state_name in CATEGORY_TO_STATE.items():
            conn.execute(
                sa.text(
                    "UPDATE work_items SET state_id = :state_id"
                    " WHERE project_id = :project_id AND category = :category"
                ),
                {
                    "state_id": state_ids[state_name],
                    "project_id": project_id,
                    "category": category,
                },
            )

    op.alter_column("work_items", "state_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_work_items_state_id_states"), "work_items", "states", ["state_id"], ["id"]
    )
    op.create_index(op.f("ix_work_items_state_id"), "work_items", ["state_id"], unique=False)
    op.drop_index(op.f("ix_work_items_category"), table_name="work_items")
    op.drop_column("work_items", "category")


def downgrade() -> None:
    op.add_column("work_items", sa.Column("category", sa.String(length=20), nullable=True))
    op.get_bind().execute(
        sa.text(
            "UPDATE work_items SET category ="
            " (SELECT category FROM states WHERE states.id = work_items.state_id)"
        )
    )
    op.alter_column("work_items", "category", nullable=False)
    op.create_index(op.f("ix_work_items_category"), "work_items", ["category"], unique=False)
    op.drop_index(op.f("ix_work_items_state_id"), table_name="work_items")
    op.drop_constraint(op.f("fk_work_items_state_id_states"), "work_items", type_="foreignkey")
    op.drop_column("work_items", "state_id")
    op.drop_table("item_labels")
    op.drop_index(op.f("ix_labels_workspace_id"), table_name="labels")
    op.drop_table("labels")
    op.drop_index(op.f("ix_states_project_id"), table_name="states")
    op.drop_table("states")
