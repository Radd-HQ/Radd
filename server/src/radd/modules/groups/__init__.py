from radd.kernel import EntityLinkSpec
from radd.kernel import EventTypeSpec, RaddPlugin

from .router import router
from .automation import PERSON_IN_GROUP_GATE
from .slq import SLQ_FIELDS
from .types import GroupEvent

plugin = RaddPlugin(
    name="groups",
    entity_links=(
        EntityLinkSpec('group', ('/settings/directory',)),
    ),
    description=(
        "Directory groups mirrored from Active Directory or LDAP, for granting access to whole groups."
    ),
    depends_on=("events", "auth"),
    weak_depends=("teams", "items"),
    slq_fields=SLQ_FIELDS,
    automation_nodes=(PERSON_IN_GROUP_GATE,),
    routers=(router,),
    event_types=(
        EventTypeSpec(GroupEvent.SYNCED, "Directory group synced", "Admin"),
        EventTypeSpec(GroupEvent.MISSING, "Directory group missing", "Admin"),
        EventTypeSpec(GroupEvent.RESTORED, "Directory group restored", "Admin"),
    ),
)
