"""The milestone EntitySpec — the north-star (docs/plugin-platform.md §1).

Declaring THIS spec is the entire feature: the kernel auto-wires the table, a
permission-guarded CRUD router, `milestone.created/updated/deleted` events (→
automations + webhooks + audit), and the `milestone.create/update/delete` RBAC
atoms — with zero edits to any other plugin or the kernel.
"""

from radd.sdk import EntityFieldSpec, EntitySpec

SPEC = EntitySpec(
    key="milestone",
    table="milestones",
    label="Milestone",
    plural="milestones",
    project_scoped=True,
    searchable=True,
    mentionable=True,
    fields=(
        EntityFieldSpec("project_id", "uuid", nullable=False, index=True, fk="projects.id"),
        EntityFieldSpec("title", "str", nullable=False),
        EntityFieldSpec("description", "text", nullable=True),
        EntityFieldSpec("due_on", "date", nullable=True),
        EntityFieldSpec("status", "str", nullable=False, default="open"),
    ),
)
