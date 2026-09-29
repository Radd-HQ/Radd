"""A subtask lives in its parent's project (RADD-1492).

Spec 80 lifted the same-project rule for the whole ladder; this release keeps it
lifted for epic <- issue and restores it for issue <- subtask, because a subtask
is a checklist line ticked in its parent's workflow. Every subtask whose parent
sits in another project becomes a top-level ISSUE in its own project — kind
flipped, parent cleared — and its keys are printed so the re-homing is on the
record. Chosen over detaching in place (a parentless subtask is invalid) and
over moving it to the parent's project (that re-keys work someone else filed).
No schema change; nothing to undo on downgrade, since the rows stay valid.

Revision ID: d1492subtaskhome
Revises: d1481leavetime
"""

import sqlalchemy as sa
from alembic import op

revision = "d1492subtaskhome"
down_revision = "d1481leavetime"
branch_labels = None
depends_on = None

CROSS_PROJECT_SUBTASKS = """
    SELECT child.id, p.key || '-' || child.number AS key
    FROM work_items AS child
    JOIN work_items AS parent ON parent.id = child.parent_id
    JOIN projects AS p ON p.id = child.project_id
    WHERE child.kind = 'subtask' AND parent.project_id <> child.project_id
"""


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(CROSS_PROJECT_SUBTASKS)).fetchall()
    if not rows:
        return
    print(
        f"RADD-1492: re-homing {len(rows)} cross-project subtask(s) as issues: "
        + ", ".join(key for _, key in rows)
    )
    bind.execute(
        sa.text(
            "UPDATE work_items SET kind = 'issue', parent_id = NULL "
            "WHERE id IN (SELECT id FROM (" + CROSS_PROJECT_SUBTASKS + ") AS cross_project)"
        )
    )


def downgrade() -> None:
    pass
