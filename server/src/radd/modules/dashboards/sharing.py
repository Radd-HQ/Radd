"""Transactional saves own rollback even when an outer service catches refusal."""

from radd.exceptions import ConflictError
from radd.modules.access import service as grants

from . import service
from .schemas import DashboardSave, DashboardTransfer
from .types import DashboardEntity


async def save(session, resource_id, data: DashboardSave, *, actor):
    async with session.begin_nested():
        manages = data.sharing is not None or data.grants is not None or data.transfer_to is not None
        resource = (await service._require_manage(session, resource_id, actor) if manages
                    else await service.require_edit(session, resource_id, actor))
        if (resource.owner_id != data.expected_owner_id
                or resource.global_access != data.expected_global_access):
            raise ConflictError(DashboardEntity.DASHBOARD,
                                reason="sharing changed since this draft was opened; review it again")
        if data.definition is not None:
            await service.update_dashboard(session, resource_id, data.definition, actor, include_shares=False)
        if data.sharing is not None:
            await service._update_sharing(session, resource, data.sharing, actor, include_shares=False)
        if data.grants is not None:
            await grants.apply_shared_grant_edits(session, service.DASHBOARD_RESOURCE,
                str(resource_id), data.grants, actor_id=actor.id)
        if data.transfer_to is not None:
            await service._transfer_ownership(session, resource,
                DashboardTransfer(user_id=data.transfer_to), actor, include_shares=False)
        return await service.hydrate_one(session, actor, resource, include_shares=False)
