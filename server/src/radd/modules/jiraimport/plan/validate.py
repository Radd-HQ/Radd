"""Checking a plan before it can provision or import (spec 100) — PURE.

Every problem names the SECTION and the SUBJECT it belongs to, so the UI can open
the right tab and highlight the right row. A plan that validates clean is one the
dry run can execute without discovering a structural mistake half way through
45,000 issues.
"""

from __future__ import annotations

import re

from radd.modules.fields.types import SELECT_TYPES, FieldType
from radd.modules.items.enums import REQUIRED_PARENT_KIND, ItemKind

from ..mapping import validate_mappings
from ..types import ComponentAction, FieldAction, UserAction, VocabAction
from .schemas import PlanMappings, PlanProblem

_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,29}")


def validate(
    mappings: PlanMappings,
    *,
    existing_fields: dict[str, FieldType],
    existing_link_type_keys: set[str],
    out_of_scope_fields: set[str] | None = None,
) -> list[PlanProblem]:
    problems: list[PlanProblem] = []
    problems += _fields(mappings, existing_fields)
    problems += _scope(mappings, out_of_scope_fields or set())
    problems += _issue_types(mappings)
    problems += _statuses(mappings)
    problems += _link_types(mappings, existing_link_type_keys)
    problems += _users(mappings)
    problems += _components(mappings, existing_fields)
    return problems


def _fields(mappings: PlanMappings, existing: dict[str, FieldType]) -> list[PlanProblem]:
    out = [
        PlanProblem(section="fields", subject=p.jira_id, message=p.message)
        for p in validate_mappings(mappings.fields, existing)
    ]
    # A create that lost its options is spec 90's dead end: switching a field to
    # `select` left `create_options` null, validation refused it, and the wizard
    # had no editor to supply them. Say what to do rather than just refusing.
    for entry in mappings.fields:
        if (
            entry.action is FieldAction.CREATE
            and entry.create_type in SELECT_TYPES
            and not entry.create_options
        ):
            out = [p for p in out if p.subject != entry.jira_id or "option set" not in p.message]
            out.append(
                PlanProblem(
                    section="fields",
                    subject=entry.jira_id,
                    message=(
                        f"'{entry.create_name or entry.target_key}' is a {entry.create_type} "
                        "with no options — add them, or switch the type to text"
                    ),
                )
            )
    return out


def _scope(mappings: PlanMappings, out_of_scope: set[str]) -> list[PlanProblem]:
    """A field that exists but is scoped to OTHER projects is not a usable target.

    Provisioning widens the scope automatically; this reports it up front so the
    dry run says so rather than the import failing per issue with "unknown field"
    — which is what a real 126-issue import hit before the widening existed.
    """
    return [
        PlanProblem(
            section="fields",
            subject=entry.jira_id,
            message=(
                f"'{entry.target_key}' is scoped to other projects — provisioning will "
                "widen it to include this one"
            ),
        )
        for entry in mappings.fields
        if entry.action is FieldAction.MAP and entry.target_key in out_of_scope
    ]


def _issue_types(mappings: PlanMappings) -> list[PlanProblem]:
    out: list[PlanProblem] = []
    active = [m for m in mappings.issue_types if m.action is not VocabAction.IGNORE]
    for entry in active:
        if entry.action is VocabAction.CREATE and not entry.type_name.strip():
            out.append(
                PlanProblem(
                    section="issue_types", subject=entry.jira, message="a type name is required"
                )
            )
    # Radd's hierarchy is epic ← issue ← subtask. A project whose issues are all
    # subtasks has nothing to parent them to, which fails per-issue at import
    # time — better to say so now.
    kinds = {m.kind for m in mappings.issue_types if m.count > 0}
    if kinds and kinds == {ItemKind.SUBTASK}:
        out.append(
            PlanProblem(
                section="issue_types",
                subject="",
                message=(
                    "every type maps to subtask, but Radd requires "
                    f"{REQUIRED_PARENT_KIND[ItemKind.SUBTASK].value} parents — "
                    "map at least one type to issue"
                ),
            )
        )
    return out


def _statuses(mappings: PlanMappings) -> list[PlanProblem]:
    out: list[PlanProblem] = []
    used = [m for m in mappings.statuses if m.count > 0]
    for entry in used:
        if entry.action is VocabAction.IGNORE:
            # An item MUST have a state, so an ignored status has nowhere to land.
            out.append(
                PlanProblem(
                    section="statuses",
                    subject=entry.jira,
                    message=(
                        f"{entry.count} issue(s) are in '{entry.jira}' — every issue needs a "
                        "state, so map it or create one"
                    ),
                )
            )
        elif not entry.state_name.strip():
            out.append(
                PlanProblem(
                    section="statuses", subject=entry.jira, message="a state name is required"
                )
            )
    return out


def _link_types(mappings: PlanMappings, existing: set[str]) -> list[PlanProblem]:
    out: list[PlanProblem] = []
    claimed: set[str] = set()
    for entry in mappings.link_types:
        if entry.action is VocabAction.IGNORE:
            continue
        if not entry.key:
            out.append(
                PlanProblem(
                    section="link_types", subject=entry.jira, message="choose a Radd link type"
                )
            )
            continue
        if not _KEY_RE.fullmatch(entry.key):
            out.append(
                PlanProblem(
                    section="link_types",
                    subject=entry.jira,
                    message=f"'{entry.key}' is not a valid link-type key",
                )
            )
            continue
        if entry.action is VocabAction.MAP and entry.key not in existing:
            out.append(
                PlanProblem(
                    section="link_types",
                    subject=entry.jira,
                    message=f"no link type '{entry.key}' exists — create it instead",
                )
            )
        if entry.action is VocabAction.CREATE:
            if entry.key in existing:
                out.append(
                    PlanProblem(
                        section="link_types",
                        subject=entry.jira,
                        message=f"'{entry.key}' already exists — map to it instead",
                    )
                )
            elif entry.key in claimed:
                out.append(
                    PlanProblem(
                        section="link_types",
                        subject=entry.jira,
                        message=f"'{entry.key}' is created twice — keys must be unique",
                    )
                )
            claimed.add(entry.key)
    return out


def _users(mappings: PlanMappings) -> list[PlanProblem]:
    out: list[PlanProblem] = []
    seen_emails: dict[str, str] = {}
    for entry in mappings.users:
        if entry.action in (UserAction.MATCH, UserAction.FALLBACK) and entry.user_id is None:
            out.append(
                PlanProblem(
                    section="users",
                    subject=entry.display_name or entry.jira_key,
                    message="pick the Radd user this person is",
                )
            )
        if entry.action is UserAction.PLACEHOLDER:
            email = entry.placeholder_email.strip().lower()
            if not email:
                out.append(
                    PlanProblem(
                        section="users",
                        subject=entry.display_name or entry.jira_key,
                        message=(
                            "Jira exposed no email and no domain is set — give an address, "
                            "or map them to an existing user instead"
                        ),
                    )
                )
            elif (other := seen_emails.get(email)) and other != entry.jira_key:
                out.append(
                    PlanProblem(
                        section="users",
                        subject=entry.display_name or entry.jira_key,
                        message=f"'{email}' is also used for {other} — two accounts would collide",
                    )
                )
            else:
                seen_emails[email] = entry.jira_key
    return out


def _components(mappings: PlanMappings, existing: dict[str, FieldType]) -> list[PlanProblem]:
    return [
        PlanProblem(
            section="components",
            subject=entry.jira,
            message=f"no custom field '{entry.target_key}' to write this into",
        )
        for entry in mappings.components
        if entry.action is ComponentAction.FIELD and entry.target_key not in existing
    ]
