from radd.kernel import PluginUiManifest, NavItemSpec
from radd.kernel import EntityLinkSpec
from radd.kernel import CrudResourceSpec, EventTypeSpec, RaddPlugin

from .admin_router import router as admin_router
from .models import VcsPendingWorklog, VcsUserLink  # noqa: F401 — Alembic autogenerate
from .router import router
from .types import VcsEntity, VcsEvent, VcsUserLinkEvent

plugin = RaddPlugin(
    name="vcs",
    ui=PluginUiManifest(nav=(NavItemSpec(key="vcs", label="Version control", path="/settings/vcs", icon="git-branch", section="settings", group="Issues", requires=("global.manage",), order=60),)),
    entity_links=(
        EntityLinkSpec('vcs_user_link', ('/settings/vcs',)),
    ),
    record_local_entities=(VcsEntity.VCS_LINK.value,),  # RADD-1328
    description=(
        "Links from issues to branches, commits and pull requests in your code hosts."
    ),
    # RADD-1258: the `vcsconn.*` atoms moved here from forgejo — every connector's
    # administration gates on them, and vcs is the module that is always loaded.
    crud_resources=(
        CrudResourceSpec("vcsconn", "global", "version-control connections", "global.manage"),
    ),
    # RADD-1369: releases + workflow for a repository's own "move merged issues"
    # and "publish version on release" switches (`policies.py`). RADD-1435:
    # automations for the system actor the connector kit writes as.
    depends_on=("projects", "auth", "events", "items", "timelogging", "workflow", "releases", "automations"),
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
