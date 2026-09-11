"""Lean labels for an administrator's current provisioning-rule window."""
import uuid
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from radd.modules.auth.models import Role
from radd.modules.projects.models import Project
from radd.modules.teams.models import Team


class ReferenceRequest(BaseModel):
    role_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    project_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    team_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class ReferenceRead(BaseModel):
    roles: dict[uuid.UUID, str]
    projects: dict[uuid.UUID, str]
    teams: dict[uuid.UUID, str]


async def read(session: AsyncSession, data: ReferenceRequest) -> ReferenceRead:
    # Caller owns the instance-admin gate; no row hydrates credentials, permissions or memberships.
    result = {}
    for name, model, label, ids in [('roles', Role, Role.name, data.role_ids),
                                    ('projects', Project, Project.key, data.project_ids),
                                    ('teams', Team, Team.name, data.team_ids)]:
        result[name] = dict((await session.execute(select(model.id, label).where(model.id.in_(set(ids))))).all()) if ids else {}
    return ReferenceRead(**result)
