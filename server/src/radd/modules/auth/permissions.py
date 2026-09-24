"""auth's OWN RBAC atoms (RADD-890).

Until this change `auth/types.py::Permission` enumerated every feature module's
atoms — `item.*`, `page.*`, `worklog.*`, `sla.*`, `vcsconn.*` — so adding a
permission to any module meant editing auth, while the kernel permissions
registry that exists for exactly that had one client (`milestones`). Two ways to
define an atom, and the one the platform advertises was used by nothing shipped.

Now every module declares the atoms it ENFORCES, and this file is auth's share:
the governance primitives whose endpoints auth actually serves.

  - `global.manage` — the instance umbrella. Not auth's feature, but auth's
    concept: it is the top of the containment ladder every other umbrella hangs
    from, and it must exist before any module can name it as its `manage`.
  - `project.create` / `project.manage` — project governance. `project.manage`
    is the project-scope umbrella the same way `global.manage` is the instance
    one; releases, views, members and issue types all name it.
  - users, roles, project membership, service accounts — the four resources
    whose tables and routers live here.

Everything else moved out. What auth kept is what auth refuses on.
"""

from radd.kernel import CrudResourceSpec, PermissionSpec

#: The two umbrellas + project creation. Declared as standalone atoms rather
#: than falling out of a CRUD resource because neither umbrella has a resource:
#: `global.manage` governs an instance, not a table.
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
    # The bespoke sentence for the user umbrella — "Manage users." (what the CRUD
    # resource below would generate) undersells it: holding it is also what makes
    # the directory readable.
    PermissionSpec(
        key="user.manage",
        scope="global",
        description="Create users and see the user directory.",
    ),
)

AUTH_CRUD_RESOURCES: tuple[CrudResourceSpec, ...] = (
    # Project ACCESS rows (ProjectMember) — the grant, not the person.
    CrudResourceSpec("member", "project", "project access", "project.manage"),
    # RADD-816 (F6): `role.read` is a deliverable atom (Baseline-seeded, so
    # day-one behaviour is the old member floor) rather than a member-floor
    # freebie — revocable for the first time.
    CrudResourceSpec(
        "role", "global", "roles", "global.manage",
        actions=("create", "read", "update", "delete"),
    ),
    # Spec 89 restored the full triple: deleting a user is real, and gated by
    # reassigning their work to a named successor rather than by the atom not
    # existing.
    CrudResourceSpec("user", "global", "users", "user.manage"),
    # Spec 113: service accounts sit beside users but are managed separately —
    # granting someone the ability to mint agent keys is not the same as granting
    # them the ability to edit people. RADD-816: no delete route exists, so no
    # delete atom is minted.
    CrudResourceSpec(
        "service_account", "global", "service accounts", "global.manage",
        actions=("create", "update"),
    ),
)
