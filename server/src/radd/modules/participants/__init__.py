from sqlalchemy import false, or_, select

from radd.kernel import EventTypeSpec, PluginUiManifest
from radd.kernel import RaddPlugin
from radd.kernel.registry import register_relation
from radd.kernel.specs import RelationSpec
from radd.modules.items.models import WorkItem

from .models import ItemParticipant
from .router import router
from .types import ParticipantEvent

# RADD-844: being shared into an item is a RELATION on it — the second-reporter
# model. `item.read@participant` + `comment.write@participant` (seeded on the
# Baseline) are what let a share actually reach someone with no standing in the
# project: they can open that one item, comment on it, and get notified — and
# nothing else. Membership lives in item_participants, not on the item row, so
# there is no pure `holds` form: gates answer it through the where-form
# (`relation_holds_row_async`), and sync resolvers fail closed. A TEAM
# participant row covers its CURRENT members — same live semantics as the
# notify fan-out.
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
    name="participants",
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Request participants (spec 72): users + whole teams following an item. "
        "Direct users are auto-watched, team rows resolve LIVE at notify "
        "fan-out time; the reporter can share their own ticket (identity "
        "check, not permission). Since RADD-844 a participant is a RELATION "
        "on the item (`@participant`): the Baseline's item.read@participant + "
        "comment.write@participant make a share confer exactly a second "
        "reporter's reach — open that item, comment, be notified."
    ),
    depends_on=("events", "projects", "auth", "teams", "items", "notify"),
    routers=(router,),
    relations=(ITEM_PARTICIPANT,),
    event_types=(
        EventTypeSpec(ParticipantEvent.ADDED, "Participant added", "Service desk", item_scoped=True),
        EventTypeSpec(ParticipantEvent.REMOVED, "Participant removed", "Service desk", item_scoped=True),
    ),
    # Federated UI (spec 94): the Participants card in the issue right-rail ships as this plugin's
    # own module-federation remote (web/remotes/participants), loaded at runtime — not baked into
    # the host. The host renders it through the `issue.panel.section` slot.
    ui=PluginUiManifest(remote="/plugins/participants/remoteEntry.js", ui_api_version="1.0.0"),
)
