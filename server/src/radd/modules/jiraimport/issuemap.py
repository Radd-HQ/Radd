"""Jira issue JSON → a decoded draft — PURE. The one definition of Jira REST v2's
value shapes (obfuscated emails, sprint beans, custom-field values, comments,
worklogs, links); every judgement is `transform`'s, from the plan."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from radd.modules.fields.types import SELECT_TYPES, FieldType

from .markup import jira_to_markdown
from .schemas import FieldMappingEntry
from .types import BuiltinTarget, FieldAction

TITLE_MAX = 500

# The PRIORITY native target's English names (see `_apply_native`).
PRIORITY_MAP = {
    "blocker": "blocker", "critical": "blocker", "highest": "high", "high": "high",
    "major": "high", "medium": "normal", "normal": "normal", "low": "low",
    "minor": "low", "lowest": "low", "trivial": "low",
}
# Jira issue-link type name → Radd link key; transform's fallback when the plan
# has no row for the type.
LINK_TYPE_MAP = {"blocks": "blocks", "duplicate": "duplicates", "cloners": "duplicates"}


def _bean_attr(blob: str, key: str) -> str | None:
    """One attribute inside a greenhopper Sprint bean toString: `key=value` up to
    the next comma or the closing bracket. `<null>` / empty read as absent."""
    m = re.search(rf"[\[,]{re.escape(key)}=(?P<v>[^,\]]*)", blob)
    if not m:
        return None
    value = m.group("v").strip()
    return None if value in ("", "<null>", "null") else value


def _date10(raw: Any) -> str | None:
    """A Jira date/datetime → its YYYY-MM-DD prefix; `<null>`/empty → None."""
    if raw is None:
        return None
    s = str(raw).strip()
    return None if s in ("", "<null>", "null") else s[:10]


def to_utc_naive(ts: str | None) -> str | None:
    if not ts:
        return None
    s = ts.strip()
    m = re.match(r"^(.*[+-]\d{2})(\d{2})$", s)  # Jira's +/-HHMM → +/-HH:MM
    if m:
        s = f"{m.group(1)}:{m.group(2)}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return ts[:19]
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat()


def decode_email(raw: str | None) -> str | None:
    """Jira obfuscates emails in the API (`a at b dot com`) — undo it."""
    if not raw:
        return None
    email = raw.replace(" at ", "@").replace(" dot ", ".").strip().lower()
    return email if "@" in email else None


def person_email(person: dict | None) -> str | None:
    """The address Jira exposed for a user object, or None — never synthesized
    (the plan's Users step decides placeholder addresses)."""
    if not person:
        return None
    return decode_email(person.get("emailAddress") or person.get("email"))


def person_key(person: dict | None) -> str:
    """Jira's stable identity for a person — username on DC, accountId on Cloud —
    which the plan's users table is keyed by, since Jira often exposes no email."""
    if not person:
        return ""
    return str(person.get("name") or person.get("key") or person.get("accountId") or "").strip()


def person_name(person: dict | None) -> str:
    if not person:
        return ""
    return person.get("displayName") or person.get("name") or ""


def comment_is_internal(comment: dict) -> bool:
    """Whether Jira limits the audience. Role/group restrictions are also carried
    separately in the draft: internal alone cannot preserve those audiences.
    """
    if comment.get("jsdPublic") is False:
        return True
    return bool(comment.get("visibility"))


@dataclass
class SprintDraft:
    """One Jira sprint an issue belongs to → a Radd cycle, with dates and completion
    so a CLOSED sprint imports as a completed cycle, not a dateless draft."""

    name: str
    state: str | None = None  # jira: future | active | closed (lower-cased)
    start_date: str | None = None  # YYYY-MM-DD
    end_date: str | None = None
    complete_date: str | None = None  # when Jira recorded the "complete sprint"


def _sprint_from_bean(blob: str) -> SprintDraft | None:
    """Parse a greenhopper Sprint `toString` blob into a SprintDraft. A plain
    string (not a bean) is taken as a bare name (guarding a runaway length)."""
    name = _bean_attr(blob, "name")
    if name is None:
        stripped = blob.strip()
        return SprintDraft(name=stripped) if 0 < len(stripped) <= 200 else None
    return SprintDraft(
        name=name,
        state=(_bean_attr(blob, "state") or "").lower() or None,
        start_date=_date10(_bean_attr(blob, "startDate")),
        end_date=_date10(_bean_attr(blob, "endDate")),
        complete_date=_date10(_bean_attr(blob, "completeDate")),
    )


def _sprints_from(raw: Any) -> list[SprintDraft]:
    """A Sprint field value → SprintDrafts (name + dates + completion). Jira returns
    either agile bean `toString` blobs or an array of dicts; both are handled. All
    of an issue's sprints are returned (its history), current one last."""
    values = raw.get("value") if isinstance(raw, dict) else raw
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    sprints: list[SprintDraft] = []
    for entry in values:
        if isinstance(entry, str):
            sprint = _sprint_from_bean(entry)
        elif isinstance(entry, dict) and entry.get("name"):
            sprint = SprintDraft(
                name=str(entry["name"]).strip(),
                state=(str(entry.get("state") or "")).lower() or None,
                start_date=_date10(entry.get("startDate")),
                end_date=_date10(entry.get("endDate")),
                complete_date=_date10(entry.get("completeDate")),
            )
        else:
            sprint = None
        if sprint and sprint.name:
            sprints.append(sprint)
    return sprints


def sprints(fields: dict, sprint_field_ids: tuple[str, ...] = ()) -> list[SprintDraft]:
    """Sprint beans from the field(s) Jira's `gh-sprint` type key names. No ids =
    no sprints: `_sprint_from_bean` accepts any short string, so parsing a guessed
    field would turn arbitrary values into cycles."""
    out: list[SprintDraft] = []
    for field_id in sprint_field_ids:
        out.extend(_sprints_from(fields.get(field_id)))
    return out


# --- custom-field value rendering (mapped fields) -----------------------------


def _scalar(value: Any) -> str | None:
    """One Jira value → a display string. A LIST yields its first non-empty
    element's scalar — NEVER `str(list)`, which would stringify a whole
    array (e.g. a Sprint bean list) into a Python repr."""
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        for key in ("value", "name", "displayName", "key"):
            if value.get(key):
                return str(value[key])
        return None
    if isinstance(value, list):
        for element in value:
            scalar = _scalar(element)
            if scalar:
                return scalar
        return None
    return str(value)


def render_value(raw: Any, radd_type: FieldType) -> Any:
    """One Jira field value → the shape a Radd field of `radd_type` stores.
    Multi-selects want a list; everything else a scalar. None when empty."""
    if raw is None or raw == [] or raw == "":
        return None
    if radd_type is FieldType.MULTI_SELECT:
        items = raw if isinstance(raw, list) else [raw]
        rendered = [_scalar(v) for v in items]
        kept = [r for r in rendered if r]
        return kept or None
    if isinstance(raw, list):
        rendered = [_scalar(v) for v in raw]
        kept = [r for r in rendered if r]
        return kept[0] if kept else None
    scalar = _scalar(raw)
    if scalar is None:
        return None
    if radd_type is FieldType.NUMBER:
        try:
            return float(scalar) if "." in scalar else int(scalar)
        except ValueError:
            return None
    if radd_type is FieldType.DATE:
        return scalar[:10]  # Jira datetime → YYYY-MM-DD
    return scalar


# --- the draft ----------------------------------------------------------------


@dataclass
class CommentDraft:
    body: str
    author_email: str | None
    created: str | None
    jira_id: str = ""  # so a re-import recognises a comment it already wrote
    author_key: str = ""  # Jira username, the stable identity the plan maps
    # RADD-1180: Jira was hiding this comment from somebody, so Radd must too.
    internal: bool = False
    restriction: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorklogDraft:
    time_spent: str  # Jira duration text ("3h 30m")
    worked_on: str | None  # YYYY-MM-DD
    author_email: str | None
    note: str
    created: str | None
    jira_id: str = ""  # for re-import dedupe (spec 100)
    author_key: str = ""


@dataclass
class LinkDraft:
    target_key: str  # the other Jira issue key
    link_type: str  # Radd link-type KEY (best-effort map; runner may refine by name)
    # Jira gives each link a direction: this issue's OUTWARD link ("this blocks X")
    # maps to source=this→target=X; an INWARD link ("this is blocked by Y") is really
    # Y→this, so the runner swaps the endpoints for inward links.
    inward: bool = False
    # The raw Jira link-type NAME, so the runner can match it to a custom Radd link
    # type by name (spec 91) instead of only the built-in fallback.
    jira_type_name: str = ""


@dataclass
class IssueDraft:
    jira_key: str
    number: int  # Radd item number = the Jira number (1:1)
    title: str
    description: str  # already markdown
    created: str | None
    labels: list[str]
    parent_jira_key: str | None
    epic_jira_key: str | None
    sprints: list[SprintDraft]
    custom_fields: dict[str, Any]
    comments: list[CommentDraft] = field(default_factory=list)
    worklogs: list[WorklogDraft] = field(default_factory=list)
    links: list[LinkDraft] = field(default_factory=list)
    # Native-target mappings: values routed into Radd features rather than custom
    # fields, resolved by transform. `native_status_name`, `assignee_email` and
    # `priority` are decoded but not yet read (the STATUS/ASSIGNEE/PRIORITY targets).
    native_team: str | None = None  # a team NAME → find-or-create
    native_status_name: str | None = None  # a workflow STATE name → find-or-create
    assignee_email: str | None = None
    priority: str | None = None
    native_watcher_emails: list[str] = field(default_factory=list)
    start_date: str | None = None  # YYYY-MM-DD
    target_date: str | None = None
    #: Story points (spec 70) — Radd's own column, not a custom field.
    estimate_points: float | None = None
    #: Jira's `updated`; without it every imported issue reads as untouched since
    #: creation, and every recently-updated view lies.
    updated: str | None = None


def jira_number(key: str) -> int:
    """'DEV-15885' → 15885 (becomes the Radd item number, preserving the ID 1:1)."""
    return int(key.rpartition("-")[2])


def _custom_field_values(
    fields: dict, mappings: list[FieldMappingEntry], catalog_types: dict[str, FieldType]
) -> dict[str, Any]:
    """Pull the MAP/CREATE-targeted Jira fields into {radd_key: value}. `catalog_types`
    gives each target key's Radd type so the value is rendered to the right shape."""
    out: dict[str, Any] = {}
    for m in mappings:
        if m.action not in (FieldAction.MAP, FieldAction.CREATE):
            continue
        radd_type = m.create_type if m.action is FieldAction.CREATE else catalog_types.get(m.target_key)
        if radd_type is None:
            continue
        rendered = render_value(fields.get(m.jira_id), radd_type)
        if rendered is None:
            continue
        # For selects, keep only values in the field's option set — filtered on the
        # RAW Jira values (which is what create_options mirrors) BEFORE any remap.
        if radd_type in SELECT_TYPES and m.create_options is not None:
            allowed = set(m.create_options)
            if radd_type is FieldType.MULTI_SELECT:
                rendered = [v for v in rendered if v in allowed] or None
            elif rendered not in allowed:
                rendered = None
        if rendered is None:
            continue
        # Per-value remap through value_map (Jira "P1" → Radd "Critical"); the
        # created field's options are rebuilt from these targets. Unmapped values
        # pass through unchanged.
        if m.value_map:
            if isinstance(rendered, list):
                rendered = [m.value_map.get(v, v) for v in rendered]
            else:
                rendered = m.value_map.get(rendered, rendered)
        out[m.target_key] = rendered
    return out


def _users_from(raw: Any) -> list[str]:
    """Jira user field value(s) → emails. Handles a single user object, an array
    of them, or a bare username string."""
    items = raw if isinstance(raw, list) else [raw]
    emails: list[str] = []
    for element in items:
        if isinstance(element, dict):
            email = person_email(element)
        else:
            email = None
        if email and email not in emails:
            emails.append(email)
    return emails


def _points(raw: Any) -> float | None:
    """A Jira story-points value → `estimate_points`, or None.

    Jira returns it as a JSON number, but a points field re-created by hand can
    arrive as a string ("3", "3.0", or "" for unset). Out-of-range values are
    dropped rather than clamped: `ItemCreate` bounds it 0-999, and silently
    turning an 8000 into 999 would invent an estimate nobody made."""
    scalar = _scalar(raw)
    if scalar is None or not str(scalar).strip():
        return None
    try:
        value = float(scalar)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 999 else None


def mapped_team(fields: dict, mappings: list[FieldMappingEntry]) -> str | None:
    """Use the same native team mapping in provisioning and item decoding."""
    name = None
    for entry in mappings:
        if entry.action is FieldAction.NATIVE and entry.builtin_target is BuiltinTarget.TEAM:
            raw = _scalar(fields.get(entry.jira_id))
            name = entry.value_map.get(raw, raw) if raw else None
    return (name.strip() or None) if name else None


def _apply_native(
    draft: IssueDraft,
    mappings: list[FieldMappingEntry],
    fields: dict,
) -> None:
    """Route NATIVE-mapped Jira fields into the draft's native slots (spec 90).
    Team/watchers resolve against the DB later (they carry names/emails here)."""
    for m in mappings:
        if m.action is not FieldAction.NATIVE or m.builtin_target is None:
            continue
        raw = fields.get(m.jira_id)
        target = m.builtin_target
        if target is BuiltinTarget.TEAM:
            draft.native_team = mapped_team(fields, mappings)
        elif target is BuiltinTarget.STATUS:
            name = _scalar(raw)
            # Only an explicit value_map entry remaps a status → a state name; an
            # unmapped status leaves native_status_name None → category fallback.
            draft.native_status_name = m.value_map.get(name) if name else None
        elif target is BuiltinTarget.WATCHERS:
            draft.native_watcher_emails = _users_from(raw)
        elif target is BuiltinTarget.PARENT:
            key = _scalar(raw)
            if key:  # an explicit parent mapping wins over the epic-link heuristic
                draft.parent_jira_key = draft.parent_jira_key or key.upper()
                draft.epic_jira_key = key.upper()
        elif target is BuiltinTarget.ASSIGNEE:
            draft.assignee_email = person_email(raw) if isinstance(raw, dict) else None
        elif target is BuiltinTarget.LABELS:
            extra = render_value(raw, FieldType.MULTI_SELECT) or []
            draft.labels = list(dict.fromkeys([*draft.labels, *extra]))
        elif target is BuiltinTarget.CYCLE:
            # The Sprint field is a list of agile beans, not a scalar — extract each
            # sprint (name + dates + completion), so a cycle is "PIPE - 116" with the
            # right status, never the whole bean blob.
            draft.sprints = [*draft.sprints, *_sprints_from(raw)]
        elif target is BuiltinTarget.PRIORITY:
            scalar = _scalar(raw)
            if scalar:
                draft.priority = PRIORITY_MAP.get(scalar.lower(), draft.priority)
        elif target is BuiltinTarget.START_DATE:
            scalar = _scalar(raw)
            draft.start_date = scalar[:10] if scalar else None
        elif target is BuiltinTarget.TARGET_DATE:
            scalar = _scalar(raw)
            draft.target_date = scalar[:10] if scalar else None
        elif target is BuiltinTarget.POINTS:
            draft.estimate_points = _points(raw)


def map_issue(
    issue: dict,
    mappings: list[FieldMappingEntry],
    catalog_types: dict[str, FieldType],
    *,
    epic_link_field: str | None = None,
    sprint_field_ids: tuple[str, ...] = (),
) -> IssueDraft:
    """One Jira `/search` issue → an IssueDraft (pure).

    `epic_link_field` and `sprint_field_ids` are resolved by the CALLER from Jira's
    stable `schema.custom` type keys (spec 100) rather than assumed here — see
    `schemakeys`. Passing nothing means "this instance has no such field", which is
    a valid answer; guessing an id is not."""
    key = issue["key"]
    fields = issue.get("fields") or {}
    parent = ((fields.get("parent") or {}).get("key")) or None
    epic = None
    if epic_link_field:
        epic = _scalar(fields.get(epic_link_field)) or None

    comments = [
        CommentDraft(
            body=jira_to_markdown(c.get("body") or ""),
            author_email=person_email(c.get("author")),
            created=to_utc_naive(c.get("created")),
            jira_id=str(c.get("id") or ""),
            author_key=person_key(c.get("author")),
            internal=comment_is_internal(c),
            restriction=c.get("visibility") or {},
        )
        for c in ((fields.get("comment") or {}).get("comments") or [])
    ]
    worklogs = [
        WorklogDraft(
            time_spent=w.get("timeSpent") or "",
            worked_on=(to_utc_naive(w.get("started")) or "")[:10] or None,
            author_email=person_email(w.get("author")),
            note=(w.get("comment") or "")[:2000],
            created=to_utc_naive(w.get("created")),
            jira_id=str(w.get("id") or ""),
            author_key=person_key(w.get("author")),
        )
        for w in ((fields.get("worklog") or {}).get("worklogs") or [])
        if w.get("timeSpent")
    ]
    links: list[LinkDraft] = []
    for link in fields.get("issuelinks") or []:
        outward = link.get("outwardIssue")
        other = outward or link.get("inwardIssue")
        if not other or not other.get("key"):
            continue
        type_name = (link.get("type") or {}).get("name") or ""
        links.append(
            LinkDraft(
                target_key=other["key"],
                link_type=LINK_TYPE_MAP.get(type_name.lower(), "relates"),
                inward=outward is None,  # inward = the other issue points at this one
                jira_type_name=type_name,
            )
        )

    draft = IssueDraft(
        jira_key=key,
        number=jira_number(key),
        title=(fields.get("summary") or key)[:TITLE_MAX],
        description=jira_to_markdown(fields.get("description") or ""),
        created=to_utc_naive(fields.get("created")),
        updated=to_utc_naive(fields.get("updated")),
        labels=[str(x) for x in (fields.get("labels") or [])],
        parent_jira_key=parent,
        epic_jira_key=epic,
        sprints=sprints(fields, sprint_field_ids),
        custom_fields=_custom_field_values(fields, mappings, catalog_types),
        comments=comments,
        worklogs=worklogs,
        links=links,
    )
    _apply_native(draft, mappings, fields)
    return draft
