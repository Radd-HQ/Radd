"""The `note` EntitySpec — declared through the PUBLIC SDK only (radd.sdk).

Declaring this is the whole backend feature: the kernel auto-wires the `acme_notes` table, a
permission-guarded CRUD router at /api/v1/notes, note.created/updated/deleted events, and the
note.create/update/delete RBAC atoms — with zero edits to Radd.
"""

from radd.sdk import EntityFieldSpec, EntitySpec

NOTE = EntitySpec(
    key="note",
    table="acme_notes",
    label="Note",
    plural="notes",
    project_scoped=True,
    fields=(
        EntityFieldSpec("project_id", "uuid", nullable=False, index=True, fk="projects.id"),
        # The issue this note is attached to (a plain uuid, so the example needs no cross-plugin FK).
        EntityFieldSpec("item_id", "uuid", nullable=True, index=True),
        EntityFieldSpec("body", "text", nullable=False),
    ),
)
