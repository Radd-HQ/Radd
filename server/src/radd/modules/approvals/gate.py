"""What `approvals` contributes to the kernel's TRANSITION_CHECK socket (RADD-1383).

`require_approval` used to be a workflow enum member that workflow validated,
evaluated and — through a `try: import approvals` that could never fail, since
plugin code is always importable — consumed. A plugin disabled at runtime kept
running from those call sites. Now the check is this object, registered on the
manifest: disabling the plugin withdraws it, and workflow fails the rules it
served CLOSED instead of reaching into a module that is switched off.

An adapter over the service, like `leave/holidays.py`: the socket asks four
questions and the answers live here, next to the lifecycle they belong to.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.auth import service as auth
from radd.modules.teams import service as teams_service
from radd.modules.workflow.types import TransitionEntity

from . import service
from .types import ApprovalCheck, ApproverKind


def _rule_error(reason: str) -> ConflictError:
    # The rule belongs to a transition row — the same 409 workflow raises for its own checks.
    return ConflictError(TransitionEntity.TRANSITION, reason=reason)


class ApprovalGate:
    """`TransitionCheckProvider` for `require_approval`."""

    check = ApprovalCheck.REQUIRE_APPROVAL.value
    # A gate someone else clears: its failure reads after the data the mover can fix.
    sort_last = True

    async def validate(self, session: AsyncSession, params: dict[str, Any]) -> dict[str, Any]:
        """Spec 107: per-entry approver rules — every entry names a real subject
        (users must be ACTIVE), team entries carry required >= 1, no duplicates.
        Display names are snapshotted server-side, never trusted from the client."""
        entries = params.get("approvers")
        if not isinstance(entries, list) or not entries:
            raise _rule_error("an approval rule needs at least one approver")
        seen: set[tuple[str, uuid.UUID]] = set()
        normalized: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise _rule_error("malformed approver entry")
            try:
                kind = ApproverKind(entry.get("kind"))
                entry_id = uuid.UUID(str(entry.get("id")))
            except ValueError:
                raise _rule_error("malformed approver entry") from None
            if (kind.value, entry_id) in seen:
                raise _rule_error("duplicate approver entry")
            seen.add((kind.value, entry_id))
            clean: dict[str, Any] = {"kind": kind.value, "id": str(entry_id)}
            if kind is ApproverKind.TEAM:
                required = entry.get("required", 1)
                if not isinstance(required, int) or isinstance(required, bool) or required < 1:
                    raise _rule_error("a team's approvals required must be >= 1")
                clean["required"] = required
            normalized.append(clean)
        user_ids = [uuid.UUID(e["id"]) for e in normalized if e["kind"] == ApproverKind.USER.value]
        team_ids = [uuid.UUID(e["id"]) for e in normalized if e["kind"] == ApproverKind.TEAM.value]
        users = await auth.users_by_ids(session, user_ids) if user_ids else {}
        teams = await teams_service.teams_by_ids(session, team_ids) if team_ids else {}
        for entry in normalized:
            entry_id = uuid.UUID(entry["id"])
            if entry["kind"] == ApproverKind.USER.value:
                user = users.get(entry_id)
                if user is None or not user.active:
                    raise _rule_error(f"unknown approver user {entry_id}")
                entry["name"] = user.name
            else:
                team = teams.get(entry_id)
                if team is None:
                    raise _rule_error(f"unknown approver team {entry_id}")
                entry["name"] = team.name
        return {**params, "approvers": normalized}

    async def prepare(self, session: AsyncSession, item) -> frozenset[str]:
        """The target state ids this item holds a consumable APPROVED request for."""
        return frozenset(await service.approved_target_state_ids(session, item.id))

    def failure(
        self, params: Mapping[str, Any], prepared: Any, to_state_id: str | None
    ) -> str | None:
        if to_state_id is not None and to_state_id in (prepared or frozenset()):
            return None
        parts: list[str] = []
        for entry in params.get("approvers") or []:
            name = entry.get("name") or entry.get("id") or "?"
            if entry.get("kind") == ApproverKind.TEAM.value:
                parts.append(f"{int(entry.get('required') or 1)} of {name}")
            else:
                parts.append(str(name))
        return f"approval required ({'; '.join(parts)})" if parts else "approval required"

    async def moved(
        self, session: AsyncSession, item_id: uuid.UUID, to_state_id: uuid.UUID
    ) -> None:
        """A move into an approved target SPENDS the unlock (one approval, one move)."""
        await service.consume(session, item_id, to_state_id)
