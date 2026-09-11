"""Transactional saves own rollback even when an outer service catches refusal."""

from radd.exceptions import ConflictError
from radd.modules.access import service as grants
from radd.modules.auth.authz import Permission

from . import service
from .schemas import ViewSave, ViewTransfer
from .types import ViewEntity


async def save(session, resource_id, data: ViewSave, *, actor):
    async with session.begin_nested():
        manages = data.sharing is not None or data.grants is not None or data.transfer_to is not None
        resource = (await service._require_manage(session, resource_id, actor, legacy_atom=Permission.VIEW_UPDATE) if manages
                    else await service._require_edit(session, resource_id, actor))
        if (resource.owner_id != data.expected_owner_id
                or resource.global_access != data.expected_global_access):
            raise ConflictError(ViewEntity.VIEW,
                                reason="sharing changed since this draft was opened; review it again")
        if data.definition is not None:
            await service.update_view(session, resource_id, data.definition, actor, include_shares=False)
        if data.sharing is not None:
            await service._update_sharing(session, resource, data.sharing, actor, include_shares=False)
        if data.grants is not None:
            await grants.apply_shared_grant_edits(session, service.VIEW_RESOURCE,
                str(resource_id), data.grants, actor_id=actor.id)
        if data.transfer_to is not None:
            await service._transfer_ownership(session, resource,
                ViewTransfer(user_id=data.transfer_to), actor, include_shares=False)
        return await service._hydrate_one(session, actor, resource, include_shares=False)
