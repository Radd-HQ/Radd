"""The `NOTIFICATION_AUDIENCE` socket provider: members of an item's participant
TEAMS. Registered on the manifest so a runtime disable withdraws it (a
`try: import` in notify could not). Direct user participants are auto-watched,
so they already arrive through the watcher list.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from . import service


class ParticipantTeamAudience:
    """`NotificationAudienceSource`: the CURRENT members of the item's
    participant teams, resolved at fan-out time."""

    async def participant_ids(self, session: AsyncSession, item_id: uuid.UUID) -> set[uuid.UUID]:
        return await service.team_recipient_ids(session, item_id)
