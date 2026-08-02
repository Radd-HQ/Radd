"""Profile → a pre-filled plan (spec 100) — PURE, so every guess is unit-tested.

The rule throughout: SUGGEST from evidence, never decide silently, and default
anything unused to ignore. Each suggestion is derived from something stable —
Jira's own `statusCategory.key`, its `schema.custom` type key, its link-type
direction names, a real email match — rather than from an English word list.

Where no stable signal exists (does "Rejected" mean done or canceled? is
"Initiative" an epic?) the suggestion is a starting point the mapping step shows
plainly, because that is a judgement only the admin can make.
"""

from __future__ import annotations

import re
import uuid

from radd.modules.items.enums import ItemKind, Priority
from radd.modules.workflow.types import StateCategory

from ..mapping import FieldMapping, slug, suggest_mappings
from ..profile import InboundProfile, PersonEntry, VocabEntry
from ..schemas import FieldMappingEntry
from ..types import ComponentAction, FieldAction, FieldBand, UserAction, VocabAction
from .schemas import (
    ComponentMapping,
    IssueTypeMapping,
    LinkTypeMapping,
    PlanMappings,
    PriorityMapping,
    SprintMapping,
    StatusMapping,
    UserMapping,
    VersionMapping,
)

# Jira's `statusCategory.key` is stable API vocabulary — the same three values on
# every instance, in every language. This is the ONLY status mapping spec 100
# hardcodes, and it is Jira's contract rather than a guess at English names.
JIRA_STATUS_CATEGORY: dict[str, StateCategory] = {
    "new": StateCategory.TODO,
    "undefined": StateCategory.TODO,
    "indeterminate": StateCategory.IN_PROGRESS,
    "done": StateCategory.DONE,
}

# Jira orders priorities by `id` — 1 is the most severe, whatever it is called.
# Position beats name: it works for P1/P2/P3, Urgent/Normal, and any translation.
_PRIORITY_LADDER: list[Priority] = [
    Priority.BLOCKER,
    Priority.HIGH,
    Priority.NORMAL,
    Priority.LOW,
]

# Radd's four built-in link types, matched against Jira's OUTWARD phrasing, which
# is stable per type ("blocks", "duplicates", "clones"). A miss is a suggestion of
# `relates`, shown as such rather than applied invisibly.
_LINK_BY_OUTWARD: dict[str, str] = {
    "blocks": "blocks",
    "duplicates": "duplicates",
    "clones": "duplicates",
    "relates to": "relates",
}


def build(
    profile: InboundProfile,
    *,
    existing_field_keys: set[str],
    existing_field_options: dict[str, list[str]] | None = None,
    users_by_email: dict[str, uuid.UUID],
    users_by_name: dict[str, uuid.UUID],
    existing_link_type_keys: set[str],
    placeholder_domain: str,
    inactive_user_ids: set[uuid.UUID] | None = None,
) -> PlanMappings:
    """One pre-filled plan. The admin adjusts; they never start from a blank sheet
    of 337 fields and 83 statuses."""
    return PlanMappings(
        fields=_fields(profile, existing_field_keys, existing_field_options or {}),
        issue_types=[_issue_type(e) for e in profile.issue_types],
        statuses=[_status(e) for e in profile.statuses],
        priorities=_priorities(profile.priorities),
        link_types=[_link_type(e, existing_link_type_keys) for e in profile.link_types],
        users=[
            _user(p, users_by_email, users_by_name, placeholder_domain, inactive_user_ids or set())
            for p in profile.people
        ],
        sprints=[_sprint(e) for e in profile.sprints],
        versions=[_version(e) for e in profile.versions],
        components=[_component(e) for e in profile.components],
    )


def _fields(
    profile: InboundProfile,
    existing_field_keys: set[str],
    existing_field_options: dict[str, list[str]],
) -> list[FieldMappingEntry]:
    """Field decisions, each carrying the evidence behind it."""
    evidence = {f.jira_id: f for f in profile.fields}
    return [
        _field(m, evidence.get(m.jira_id), existing_field_options)
        for m in suggest_mappings(profile.fields, existing_field_keys)
    ]


def _field(
    mapping: FieldMapping, field, existing_field_options: dict[str, list[str]]
) -> FieldMappingEntry:
    """The pure suggester deals in dataclasses; the plan stores wire models."""
    observed = list(field.distinct_values or []) if field else []
    # Mapping into an existing select whose options do not cover the data: suggest
    # ADDING them. The alternative is silently dropping real values, which is what
    # cost seven issues a field value on a live 126-issue import.
    target_options = existing_field_options.get(mapping.target_key)
    extend = False
    if mapping.action is FieldAction.MAP and target_options is not None and observed:
        known = {v.casefold() for v in target_options}
        extend = any(v.casefold() not in known for v in observed)
    return FieldMappingEntry(
        jira_id=mapping.jira_id,
        jira_name=mapping.jira_name,
        action=mapping.action,
        target_key=mapping.target_key,
        create_type=mapping.create_type,
        create_name=mapping.create_name,
        create_options=mapping.create_options,
        create_scope=mapping.create_scope,
        builtin_target=mapping.builtin_target,
        value_map=dict(mapping.value_map),
        band=field.band if field else FieldBand.IN_USE,
        band_reason=field.band_reason if field else "",
        populated=field.populated if field else 0,
        samples=list(field.samples[:3]) if field else [],
        extend_options=extend,
        observed_values=observed,
    )


# --- issue types --------------------------------------------------------------

# Jira marks subtask types in the catalog (`subtask: true`); everything else needs
# a judgement. "Epic" is Jira's own reserved type name and is safe to recognise —
# it is the one type Jira Software itself special-cases.
_EPIC_HINTS = {"epic"}


def _issue_type(entry: VocabEntry) -> IssueTypeMapping:
    """A Jira issue type → the hierarchy kind + a Radd issue type.

    Spec 90 collapsed this to `"epic" in name` / `"sub" in name`, so "Initiative",
    "Milestone" and any renamed or translated type silently became a plain issue
    with no way to correct it. Both axes are now editable rows.
    """
    lowered = entry.value.strip().lower()
    if entry.meta.get("subtask") or lowered.replace("-", " ").startswith("sub"):
        kind = ItemKind.SUBTASK
    elif lowered in _EPIC_HINTS:
        kind = ItemKind.EPIC
    else:
        kind = ItemKind.ISSUE
    return IssueTypeMapping(
        jira=entry.value,
        count=entry.count,
        kind=kind,
        # Unused types are ignored: they exist on the instance but not in this
        # project, so creating a Radd issue type for each would be pure clutter.
        action=VocabAction.IGNORE if entry.unused else VocabAction.CREATE,
        type_name=entry.value[:100],
    )


# --- statuses -----------------------------------------------------------------


def _status(entry: VocabEntry) -> StatusMapping:
    """A Jira status → a Radd state + category, seeded from Jira's own category key.

    Note what is NOT guessed: `canceled`. Jira has no cancelled category — it
    files "Rejected", "Won't Do" and "Abandoned" under `done` — so spec 90 tested
    the literal names "cancelled"/"canceled" and got everything else wrong. The
    suggestion follows Jira, and the admin retargets the ones that mean cancelled.
    """
    category = JIRA_STATUS_CATEGORY.get(
        str(entry.meta.get("category_key", "")).lower(), StateCategory.TODO
    )
    return StatusMapping(
        jira=entry.value,
        count=entry.count,
        action=VocabAction.IGNORE if entry.unused else VocabAction.CREATE,
        state_name=entry.value[:100],
        category=category,
    )


# --- priorities ---------------------------------------------------------------


def _priorities(entries: list[VocabEntry]) -> list[PriorityMapping]:
    """Map by Jira's own severity ORDER, not by name.

    Jira numbers priorities from most to least severe, so position carries the
    meaning that "P1"/"Urgent"/"Bloquant" do not share. The used values are ranked
    by their Jira id and spread across Radd's four levels; unused ones sit at
    normal, ignored.
    """
    # Rank over the WHOLE ladder, not just the values this project happens to use:
    # "P2" means the same thing whether or not anyone filed a P1, and its position
    # among all five is what decides where it lands.
    ordered = sorted(entries, key=lambda e: (_int_or_max(e.meta.get("id")), e.value.lower()))
    assigned: dict[str, Priority] = {}
    for index, entry in enumerate(ordered):
        if len(ordered) <= 1:
            assigned[entry.value] = Priority.NORMAL
        else:
            slot = round(index * (len(_PRIORITY_LADDER) - 1) / (len(ordered) - 1))
            assigned[entry.value] = _PRIORITY_LADDER[slot]
    return [
        PriorityMapping(
            jira=e.value, count=e.count, priority=assigned.get(e.value, Priority.NORMAL)
        )
        for e in entries
    ]


def _int_or_max(raw: object) -> int:
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return 1_000_000


# --- link types ---------------------------------------------------------------


def _link_type(entry: VocabEntry, existing_keys: set[str]) -> LinkTypeMapping:
    """A Jira link type → a Radd one, matched on Jira's OUTWARD phrase.

    The outward phrase is the stable part of a Jira link type ("blocks",
    "duplicates", "clones"); the display NAME is free text an admin renamed. Spec
    90 matched the name against three literals and defaulted the rest to
    `relates`, so "Implements", "Issue split" and "Problem/Incident" all silently
    became the same relationship.
    """
    outward = str(entry.meta.get("outward", "")).strip().lower()
    key = _LINK_BY_OUTWARD.get(outward, "")
    if not key:
        candidate = slug(entry.value)[:30]
        # An unrecognised type is worth CREATING (spec 91 made link types
        # definable) rather than flattening into `relates` and losing the meaning.
        if candidate and candidate not in existing_keys and not entry.unused:
            return LinkTypeMapping(
                jira=entry.value,
                count=entry.count,
                action=VocabAction.CREATE,
                key=candidate,
                outward_name=(entry.meta.get("outward") or entry.value)[:60],
                inward_name=(entry.meta.get("inward") or entry.value)[:60],
            )
        key = "relates"
    return LinkTypeMapping(
        jira=entry.value,
        count=entry.count,
        action=VocabAction.IGNORE if entry.unused else VocabAction.MAP,
        key=key,
    )


# --- people -------------------------------------------------------------------


def _user(
    person: PersonEntry,
    users_by_email: dict[str, uuid.UUID],
    users_by_name: dict[str, uuid.UUID],
    placeholder_domain: str,
    inactive_user_ids: set[uuid.UUID],
) -> UserMapping:
    """Match a Jira person to a Radd user, or say plainly that we could not.

    An exact email match is the account, full stop (the spec-88 rule). A display
    name match is offered too, but as a *suggestion with its reason shown*, since
    two people can share a name.

    Where nothing matches, the default is a placeholder — but the synthesized
    address is put in the row for the admin to see BEFORE anything is created.
    Spec 90 invented it on a hardcoded company domain and created the account
    silently.
    """
    email = person.email.strip().lower()
    if email and (matched := users_by_email.get(email)):
        return UserMapping(
            jira_key=person.key,
            display_name=person.display_name,
            jira_email=person.email,
            count=person.count,
            roles=person.sorted_roles,
            action=UserAction.MATCH,
            user_id=matched,
            matched_inactive=matched in inactive_user_ids,
            match_reason=(
                f"same email address ({person.email})"
                + (" — deactivated, but their history is kept"
                   if matched in inactive_user_ids else "")
            ),
        )
    name = person.display_name.strip().lower()
    if name and (matched := users_by_name.get(name)):
        return UserMapping(
            jira_key=person.key,
            display_name=person.display_name,
            jira_email=person.email,
            count=person.count,
            roles=person.sorted_roles,
            action=UserAction.MATCH,
            user_id=matched,
            matched_inactive=matched in inactive_user_ids,
            match_reason="same display name — check this is the same person",
        )
    return UserMapping(
        jira_key=person.key,
        display_name=person.display_name,
        jira_email=person.email,
        count=person.count,
        roles=person.sorted_roles,
        action=UserAction.PLACEHOLDER,
        placeholder_email=placeholder_email(person, placeholder_domain),
        match_reason="nobody in Radd matches — a placeholder keeps their work theirs",
    )


_USERNAME_RE = re.compile(r"[a-z0-9._-]+")


def placeholder_email(person: PersonEntry, domain: str) -> str:
    """The address a placeholder would get: Jira's own, else `<username>@<domain>`.

    Empty when there is no domain — the Users step then shows the person with no
    address rather than inventing one, which is the whole point of the change.
    """
    if person.email:
        return person.email
    username = person.key.strip().lower()
    if domain and username and _USERNAME_RE.fullmatch(username):
        return f"{username}@{domain}"
    return ""


# --- sprints, versions, components --------------------------------------------


def _sprint(entry: VocabEntry) -> SprintMapping:
    return SprintMapping(
        jira=entry.value,
        count=entry.count,
        action=VocabAction.IGNORE if entry.unused else VocabAction.CREATE,
        state=str(entry.meta.get("state", "")),
        start_date=str(entry.meta.get("start_date", "")),
        end_date=str(entry.meta.get("end_date", "")),
        complete_date=str(entry.meta.get("complete_date", "")),
    )


def _version(entry: VocabEntry) -> VersionMapping:
    return VersionMapping(
        jira=entry.value,
        count=entry.count,
        action=VocabAction.IGNORE if entry.unused else VocabAction.CREATE,
    )


def _component(entry: VocabEntry) -> ComponentMapping:
    """Radd has no component concept, so a label is the lossless default — it keeps
    the value visible and filterable without inventing a structure."""
    return ComponentMapping(
        jira=entry.value,
        count=entry.count,
        action=ComponentAction.IGNORE if entry.unused else ComponentAction.LABEL,
    )
