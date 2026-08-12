"""Applies the pure alert plans (planner.py): item creation, dedup comments, and
the optional resolve transition — all as the SYSTEM actor through the items,
comments, and workflow seams."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.automations.intake import suppressed as intake_suppressed
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.comments import service as comments
from radd.modules.comments.schemas import CommentCreate
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.workflow import service as workflow
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import planner
from .models import AlertItem
from .types import ALERT_LABEL, AlertAction, AlertEntity

logger = logging.getLogger(__name__)


async def process(session: AsyncSession, payload: dict) -> dict[str, int]:
    """Plan (pure) + apply one Alertmanager webhook delivery."""
    fingerprints = {
        alert.get("fingerprint", "") for alert in payload.get("alerts") or []
    } - {""}
    known = await _known_items(session, fingerprints)
    plans = planner.plan_alerts(payload, existing=frozenset(known))
    if not plans:
        return {"created": 0, "commented": 0, "transitioned": 0}

    project = await _target_project(session)
    actor = await auth.get_user(session, SYSTEM_ACTOR_ID)
    created = commented = transitioned = 0
    for plan in plans:
        if plan.action is AlertAction.CREATE:
            # Machine intake is not human intake (spec 119). A monitoring system
            # firing an alert cannot be asked for repro steps: enforcing a
            # required check here answers Alertmanager with a 5xx, which it
            # retries, and the alert that nobody can see is the one that matters.
            with intake_suppressed():
                item = await items.create_item(
                    session,
                    ItemCreate(
                        project_id=project.id,
                        title=plan.title,
                        description=plan.description,
                        labels=[ALERT_LABEL],
                    ),
                    actor,
                )
            session.add(AlertItem(fingerprint=plan.fingerprint, item_id=item.id))
            await session.flush()
            created += 1
            continue
        item_id = known[plan.fingerprint]
        await comments.create_comment(session, item_id, CommentCreate(body=plan.comment), actor)
        commented += 1
        if plan.action is AlertAction.RESOLVED and settings.alertmanager_resolve_state:
            transitioned += await _transition_resolved(session, item_id, actor)
    return {"created": created, "commented": commented, "transitioned": transitioned}


async def _known_items(
    session: AsyncSession, fingerprints: set[str]
) -> dict[str, uuid.UUID]:
    if not fingerprints:
        return {}
    result = await session.execute(
        select(AlertItem.fingerprint, AlertItem.item_id).where(
            AlertItem.fingerprint.in_(fingerprints)
        )
    )
    return dict(result.all())


async def _target_project(session: AsyncSession) -> Project:
    key = settings.alertmanager_project_key.upper()
    if not key:
        raise ConflictError(AlertEntity.ALERT, reason="RADD_ALERTMANAGER_PROJECT_KEY is unset")
    projects = await projects_service.list_projects(session)
    project = next((p for p in projects if p.key == key), None)
    if project is None:
        raise ConflictError(AlertEntity.ALERT, reason=f"no project with key {key}")
    return project


async def _transition_resolved(
    session: AsyncSession, item_id: uuid.UUID, actor: User
) -> int:
    """Move the item to the configured resolve state (name match; missing/already
    -there = skip) — mirrors the gitlab/forgejo merge transition."""
    target_name = settings.alertmanager_resolve_state
    item = await items.require_item(session, item_id)
    states = await workflow.list_states(session, item.project_id)
    target = next((state for state in states if state.name == target_name), None)
    if target is None or item.state_id == target.id:
        return 0
    try:
        await items.update_item(session, item.id, ItemUpdate(state_id=target.id), actor)
        return 1
    except Exception:
        logger.exception("alertmanager: resolve transition failed for item %s", item.id)
        return 0
