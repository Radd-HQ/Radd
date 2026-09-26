"""auth's OWN RBAC atoms (RADD-890): the instance and project umbrellas,
project creation/deletion, and the four resources whose tables and routers
live here (users, roles, project access, service accounts). Every other atom
is declared by the module that enforces it."""

from radd.kernel import CrudResourceSpec, PermissionSpec

#: Standalone atoms: no CRUD resource owns them (`global.manage` governs an instance).
AUTH_PERMISSIONS: tuple[PermissionSpec, ...] = (
    PermissionSpec(
        key="global.manage",
        scope="global",
        description="Administer global settings and shared configuration.",
    ),
    PermissionSpec(
        key="project.create",
        scope="global",
        description="Create projects (global).",
        # RADD-1305: `global.manage` already implied project.DELETE; creating
        # one is the smaller power, so leaving it out was an incoherent line.
        implied_by=("global.manage",),
    ),
    PermissionSpec(
        key="project.manage",
        scope="project",
        description="Manage a project: states, fields, labels, teams, members.",
    ),
    # RADD-1174: GLOBAL, deliberately, like `project.create`. Were it
    # project-scoped it would join `PROJECT_PERMISSIONS`, which is the builtin
    # project Manager role's grant set — and a delegated project admin must not be
    # able to destroy the project they were handed. Rides `global.manage`.
    PermissionSpec(
        key="project.delete",
        scope="global",
        description="Delete a project and everything in it (global).",
        implied_by=("global.manage",),
    ),
    # Bespoke sentence: holding it is also what makes the directory readable.
    PermissionSpec(
        key="user.manage",
        scope="global",
        description="Create users and see the user directory.",
    ),
)

AUTH_CRUD_RESOURCES: tuple[CrudResourceSpec, ...] = (
    # Project access: the project-scoped grant rows, not the person.
    CrudResourceSpec("member", "project", "project access", "project.manage"),
    # RADD-816: role.read is Baseline-seeded but revocable.
    CrudResourceSpec(
        "role", "global", "roles", "global.manage",
        actions=("create", "read", "update", "delete"),
    ),
    CrudResourceSpec("user", "global", "users", "user.manage"),
    # Spec 113: minting agent keys is not editing people. No delete route, so no
    # delete atom.
    CrudResourceSpec(
        "service_account", "global", "service accounts", "global.manage",
        actions=("create", "update"),
    ),
)
