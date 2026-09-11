"""SQL visibility for globally scoped hierarchical resources.

Mirrors effective_level's exact-level deny rule, with intrinsic ownership.
Callers still own their resource's admission gate (e.g. a readable project).
"""
from sqlalchemy import String, and_, case, cast, false, or_, select

from .models import AccessGrant
from .registry import ResourceSpec
from .resolution import SubjectContext
from .types import GrantEffect, GrantSubject


def _level_clauses(spec: ResourceSpec, context: SubjectContext, *, resource_id,
                   global_access, live):
    if not spec.hierarchical or spec.project_scoped:
        raise ValueError("shared visibility requires a globally scoped hierarchical resource")
    subject = or_(
        and_(AccessGrant.subject_type == GrantSubject.USER, AccessGrant.subject_id == context.user_id),
        and_(AccessGrant.subject_type == GrantSubject.TEAM, AccessGrant.subject_id.in_(context.team_ids)),
        and_(AccessGrant.subject_type == GrantSubject.GROUP, AccessGrant.subject_id.in_(context.group_ids)),
        and_(AccessGrant.subject_type == GrantSubject.ROLE, AccessGrant.subject_id.in_(context.role_ids)),
    )
    matching = select(AccessGrant.id).where(
        AccessGrant.resource_type == spec.resource_type,
        AccessGrant.resource_id == cast(resource_id, String),
        AccessGrant.project_id.is_(None), live, subject,
    ).correlate_except(AccessGrant)
    levels = []
    for level in spec.accesses:
        at_level = matching.where(AccessGrant.access == level)
        allowed = at_level.where(AccessGrant.effect != GrantEffect.DENY).exists()
        denied = at_level.where(AccessGrant.effect == GrantEffect.DENY).exists()
        levels.append(and_(or_(global_access == level, allowed), ~denied))
    return levels


def visible_clause(spec: ResourceSpec, context: SubjectContext, *, resource_id,
                   owner_id, global_access, live):
    levels = _level_clauses(spec, context, resource_id=resource_id,
                           global_access=global_access, live=live)
    return or_(owner_id == context.user_id, *levels) if levels else false()


def state_expressions(spec: ResourceSpec, context: SubjectContext, *, resource_id,
                      global_access, live):
    """One effective level and sharing flag per resource, without grant hydration."""
    levels = _level_clauses(spec, context, resource_id=resource_id,
                           global_access=global_access, live=live)
    level = case(*reversed(list(zip(levels, spec.accesses))), else_=None)
    shared = select(AccessGrant.id).where(
        AccessGrant.resource_type == spec.resource_type,
        AccessGrant.resource_id == cast(resource_id, String),
        AccessGrant.effect == GrantEffect.ALLOW, live,
    ).correlate_except(AccessGrant).exists()
    return level, shared
