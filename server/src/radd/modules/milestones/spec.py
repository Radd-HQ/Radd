"""The milestone EntitySpec. Declaring it is the entire feature: the kernel
auto-wires the table, a permission-guarded CRUD router, the `milestone.*` events
(automations, webhooks, audit) and the `milestone.create/update/delete` atoms."""

from radd.sdk import EntityFieldSpec, EntitySpec

SPEC = EntitySpec(
    key="milestone",
    table="milestones",
    label="Milestone",
    plural="milestones",
    project_scoped=True,
    searchable=True,
    mentionable=True,
    # RADD-1327: the page its `#` mentions and audit entries link to.
    url="/milestones#milestone-{id}",
    fields=(
        EntityFieldSpec("project_id", "uuid", nullable=False, index=True, fk="projects.id"),
        EntityFieldSpec("title", "str", nullable=False),
        EntityFieldSpec("description", "text", nullable=True),
        EntityFieldSpec("due_on", "date", nullable=True),
        EntityFieldSpec("status", "str", nullable=False, default="open"),
    ),
)
