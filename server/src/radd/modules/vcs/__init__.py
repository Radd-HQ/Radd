from radd.kernel import CrudResourceSpec, EventTypeSpec, RaddPlugin

from .admin_router import router as admin_router
from .models import VcsPendingWorklog, VcsUserLink  # noqa: F401 — Alembic autogenerate
from .router import router
from .types import VcsEvent, VcsUserLinkEvent

plugin = RaddPlugin(
    name="vcs",
    description=(
        "Links from issues to branches, commits and pull requests in your code hosts."
    ),
    # RADD-1258: the `vcsconn.*` atoms moved here from forgejo — every connector's
    # administration gates on them, and vcs is the module that is always loaded.
    crud_resources=(
        CrudResourceSpec("vcsconn", "global", "version-control connections", "global.manage"),
    ),
    depends_on=("projects", "auth", "events", "items", "timelogging"),
    routers=(router, admin_router),
    event_types=(
        EventTypeSpec(VcsEvent.LINKED, "VCS ref linked", "Links", item_scoped=True),
        EventTypeSpec(
            VcsEvent.UPDATED, "VCS ref updated", "Links", item_scoped=True, has_changes=True
        ),
        EventTypeSpec(VcsEvent.UNLINKED, "VCS ref unlinked", "Links", item_scoped=True),
        # Spec 123: identity-map administration is audited; not a trigger.
        EventTypeSpec(
            VcsUserLinkEvent.CREATED, "VCS account mapped", "Admin",
            trigger=False, entity_type="vcs_user_link",
        ),
        EventTypeSpec(
            VcsUserLinkEvent.DELETED, "VCS account unmapped", "Admin",
            trigger=False, entity_type="vcs_user_link",
        ),
    ),
)
