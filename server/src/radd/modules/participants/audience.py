"""What participants adds to an issue's notification audience (RADD-1385).

The kernel `NOTIFICATION_AUDIENCE` socket's provider. `notify` used to import
`service.team_recipient_ids` behind a `try: import` that could never fail —
plugin code is always importable — so a participants plugin disabled at runtime
went on widening every item's audience. Registered on the manifest instead,
disabling the plugin withdraws it with the rest of the plugin.

Only the TEAM half: a direct user participant was auto-watched when added, so
they already arrive through the watcher list.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from . import service


class ParticipantTeamAudience:
    """`NotificationAudienceSource`: the CURRENT members of the item's
    participant teams, resolved at fan-out time."""

    async def participant_ids(self, session: AsyncSession, item_id: uuid.UUID) -> set[uuid.UUID]:
        return await service.team_recipient_ids(session, item_id)
