from sqlalchemy import false, or_, select

from radd.kernel import EventTypeSpec, IntegrationSpec, PermissionSpec, PluginUiManifest, ProjectRelationSpec
from radd.kernel import RaddPlugin
from radd.kernel.sockets import Socket
from radd.kernel.registry import register_relation
from radd.kernel.specs import RelationSpec
from radd.modules.items.models import WorkItem

from .models import ItemParticipant
from . import mcptools, service
from .automation import ADD_PARTICIPANT_NODE
from .audience import ParticipantTeamAudience
from .router import router
from .types import PARTICIPANT_MANAGE, TEAM_AUDIENCE, ParticipantEvent

# Being shared into an item is a RELATION on it (RADD-844). Membership lives in
# item_participants, so there is no pure `holds` form: gates use the where-form
# (`relation_holds_row_async`) and sync resolvers fail closed. A team row covers
# its CURRENT members.
ITEM_PARTICIPANT = RelationSpec(
    resource="item",
    key="participant",
    label="shared with them",
    where=lambda actor: WorkItem.id.in_(
        select(ItemParticipant.item_id).where(
            or_(
                ItemParticipant.user_id == actor.user_id,
                ItemParticipant.team_id.in_(actor.team_ids) if actor.team_ids else false(),
            )
        )
    ),
    holds=None,
    expensive=True,
)
register_relation(ITEM_PARTICIPANT)

plugin = RaddPlugin(
    # RADD-937: being shared into an item makes its project visible — the
    # same "second reporter" reading the relation above already has.
    project_relations=(
        ProjectRelationSpec(
            key="participant",
            label="you are a participant on an item here",
            resolve=service.projects_with_participation,
        ),
    ),
    name="participants",
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Participants: people and teams who follow a request alongside its reporter."
    ),
    depends_on=("events", "projects", "auth", "teams", "items", "notify"),
    routers=(router,),
    # RADD-1236: the roster over MCP — by item key, person by email, team by name.
    mcp_tools=mcptools.MCP_TOOLS,
    # RADD-1387: Add participant is this plugin's automation action (key
    # `action.add_participant`, kept from when it was built in) — disabled,
    # it leaves the catalog with the plugin instead of being called anyway.
    automation_nodes=(ADD_PARTICIPANT_NODE,),
    relations=(ITEM_PARTICIPANT,),
    # RADD-1304: sharing an issue is a grant, not an identity check. `@own`
    # means "issues they reported" — the atom takes the ITEM's relations.
    permissions=(
        PermissionSpec(
            PARTICIPANT_MANAGE,
            "project",
            "Add and remove an issue's participants.",
            implied_by=("item.update",),
        ),
    ),
    relation_domains=((PARTICIPANT_MANAGE, "item"),),
    # RADD-1385: team participants widen an item's notification audience through
    # the kernel socket notify reads — withdrawn with the plugin on disable.
    integrations=(
        IntegrationSpec(Socket.NOTIFICATION_AUDIENCE, TEAM_AUDIENCE, impl=ParticipantTeamAudience()),
    ),
    event_types=(
        EventTypeSpec(ParticipantEvent.ADDED, "Participant added", "Service desk", item_scoped=True),
        EventTypeSpec(ParticipantEvent.REMOVED, "Participant removed", "Service desk", item_scoped=True),
    ),
    # Federated UI: the issue rail's Participants card (issue.panel.section slot).
    ui=PluginUiManifest(remote="/plugins/participants/remoteEntry.js", ui_api_version="1.0.0"),
)
