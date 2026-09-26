"""RADD-1394: the SLA list column / card cell is the slas plugin's `slas.timer`.

Plugins contribute list columns and board-card cells through the UI SDK, and a
contributed attribute's id is namespaced by its plugin (`<plugin>.<name>`), so it
can never collide with a builtin column, a `cf.<key>` custom field or another
plugin. The SLA timer was the host's builtin `sla` until this version; the stored
id is rewritten in place rather than carried as a namespace exception:

* `views.columns` — the list's ordered column ids;
* `views.card_layout.cells[].attr` — the board card layout;
* `card_layout_presets.layout.cells[].attr` — saved card presets.

Everything else in those documents is untouched. Downgrade restores `sla`.

Revision ID: d1394slacols
Revises: d1370alertpolicy
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "d1394slacols"
down_revision = "d1370alertpolicy"
branch_labels = None
depends_on = None

OLD = "sla"
NEW = "slas.timer"


def _as_json(value):
    return json.loads(value) if isinstance(value, str) else value


def _columns(columns, old: str, new: str):
    if not isinstance(columns, list) or old not in columns:
        return None
    return [new if column == old else column for column in columns]


def _layout(layout, old: str, new: str):
    if not isinstance(layout, dict) or not isinstance(layout.get("cells"), list):
        return None
    cells = layout["cells"]
    if not any(isinstance(cell, dict) and cell.get("attr") == old for cell in cells):
        return None
    return {
        **layout,
        "cells": [
            {**cell, "attr": new} if isinstance(cell, dict) and cell.get("attr") == old else cell
            for cell in cells
        ],
    }


def _rename(old: str, new: str) -> None:
    bind = op.get_bind()
    views = bind.execute(
        sa.text("SELECT id, columns, card_layout FROM views WHERE columns IS NOT NULL OR card_layout IS NOT NULL")
    ).fetchall()
    for row in views:
        columns = _columns(_as_json(row.columns), old, new)
        layout = _layout(_as_json(row.card_layout), old, new)
        if columns is not None:
            bind.execute(
                sa.text("UPDATE views SET columns = CAST(:value AS jsonb) WHERE id = :id"),
                {"id": row.id, "value": json.dumps(columns)},
            )
        if layout is not None:
            bind.execute(
                sa.text("UPDATE views SET card_layout = CAST(:value AS jsonb) WHERE id = :id"),
                {"id": row.id, "value": json.dumps(layout)},
            )
    presets = bind.execute(sa.text("SELECT id, layout FROM card_layout_presets")).fetchall()
    for row in presets:
        layout = _layout(_as_json(row.layout), old, new)
        if layout is not None:
            bind.execute(
                sa.text("UPDATE card_layout_presets SET layout = CAST(:value AS jsonb) WHERE id = :id"),
                {"id": row.id, "value": json.dumps(layout)},
            )


def upgrade() -> None:
    _rename(OLD, NEW)


def downgrade() -> None:
    _rename(NEW, OLD)
