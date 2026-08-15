"""One cached Jira issue + a plan → an item draft (spec 100) — PURE.

Wraps `issuemap` (the spec-90 decoder, which still does the hard work of reading
Jira's value shapes) and replaces every place it USED to guess with a lookup into
the plan:

    spec 90                                  spec 100
    `"epic" in name` / `"sub" in name`   →   the issue-type table's `kind`
    PRIORITY_MAP (English)               →   the priority table
    CATEGORY_MAP + a test for "cancelled"→   the status table's category
    LINK_TYPE_MAP (three names)          →   the link-type table
    `fields["customfield_10002"]`        →   ids resolved from `gh-sprint`
    `<user>@acme.example`                →   the users table's decision

Nothing here reads the database or the network, so the dry run and the real
import share one code path and cannot disagree about what would happen.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from radd.modules.fields.types import FieldType
from radd.modules.items.enums import ItemKind, Priority
from radd.modules.workflow.types import StateCategory

from . import issuemap
from .plan.schemas import PlanMappings
from .types import ComponentAction, UserAction, VocabAction


@dataclass(frozen=True)
class Vocab:
    """The plan's vocabularies, indexed for lookup. Built once per run."""

    kind_by_type: dict[str, ItemKind]
    type_id_by_type: dict[str, uuid.UUID]
    ignored_types: frozenset[str]
    state_id_by_status: dict[str, uuid.UUID]
    category_by_status: dict[str, StateCategory]
    priority_by_name: dict[str, Priority]
    link_key_by_name: dict[str, str]
    ignored_links: frozenset[str]
    user_id_by_key: dict[str, uuid.UUID]
    # Jira exposes some authors only by email, so the plan's addresses are indexed
    # too — both routes land on the same decision the Users step made.
    user_id_by_email: dict[str, uuid.UUID]
    skipped_users: frozenset[str]
    cycle_names: frozenset[str]
    version_names: frozenset[str]
    component_action: ComponentAction
    component_field_key: str
    # Allowed options per select-like target field. A Jira value outside the set
    # is DROPPED from that field rather than failing the whole issue — losing one
    # field value is recoverable, losing the issue is not.
    field_options: dict[str, frozenset[str]]
    sprint_field_ids: tuple[str, ...]
    epic_link_field_id: str

    @classmethod
    def of(
        cls,
        mappings: PlanMappings,
        *,
        state_ids: dict[str, uuid.UUID],
        type_ids: dict[str, uuid.UUID],
        user_ids: dict[str, uuid.UUID],
        sprint_field_ids: tuple[str, ...],
        epic_link_field_id: str,
        field_options: dict[str, frozenset[str]] | None = None,
    ) -> "Vocab":
        component = next(
            (c for c in mappings.components if c.action is ComponentAction.FIELD), None
        )
        return cls(
            kind_by_type={m.jira: m.kind for m in mappings.issue_types},
            type_id_by_type=type_ids,
            ignored_types=frozenset(
                m.jira for m in mappings.issue_types if m.action is VocabAction.IGNORE
            ),
            state_id_by_status=state_ids,
            category_by_status={m.jira: m.category for m in mappings.statuses},
            priority_by_name={m.jira: m.priority for m in mappings.priorities},
            link_key_by_name={
                m.jira: m.key for m in mappings.link_types if m.action is not VocabAction.IGNORE
            },
            ignored_links=frozenset(
                m.jira for m in mappings.link_types if m.action is VocabAction.IGNORE
            ),
            user_id_by_key=user_ids,
            user_id_by_email={
                address.lower(): resolved
                for m in mappings.users
                if (resolved := user_ids.get(m.jira_key)) is not None
                for address in (m.jira_email, m.placeholder_email)
                if address
            },
            skipped_users=frozenset(
                m.jira_key for m in mappings.users if m.action is UserAction.SKIP
            ),
            cycle_names=frozenset(
                m.jira for m in mappings.sprints if m.action is not VocabAction.IGNORE
            ),
            version_names=frozenset(
                m.jira for m in mappings.versions if m.action is not VocabAction.IGNORE
            ),
            component_action=(
                mappings.components[0].action if mappings.components else ComponentAction.IGNORE
            ),
            component_field_key=component.target_key if component else "",
            field_options=field_options or {},
            sprint_field_ids=sprint_field_ids,
            epic_link_field_id=epic_link_field_id,
        )


@dataclass
class ItemDraft:
    """Everything one Jira issue becomes, resolved to Radd ids where possible."""

    jira_key: str
    number: int
    title: str
    description: str
    kind: ItemKind
    type_id: uuid.UUID | None
    state_id: uuid.UUID | None
    state_category: StateCategory
    priority: Priority
    assignee_id: uuid.UUID | None
    reporter_id: uuid.UUID | None
    created: str | None
    updated: str | None
    labels: list[str] = field(default_factory=list)
    custom_fields: dict = field(default_factory=dict)
    parent_jira_key: str = ""
    epic_jira_key: str = ""
    sprint_names: list[str] = field(default_factory=list)
    version_names: list[str] = field(default_factory=list)
    watcher_ids: list[uuid.UUID] = field(default_factory=list)
    estimate_points: float | None = None
    start_date: str | None = None
    target_date: str | None = None
    links: list["LinkDraft"] = field(default_factory=list)
    comments: list["CommentDraft"] = field(default_factory=list)
    worklogs: list["WorklogDraft"] = field(default_factory=list)
    attachment_ids: list[str] = field(default_factory=list)
    # The raw Jira vocabulary values, so a problem can name the MAPPING ROW that
    # caused it rather than only the issue it happened to.
    status_name: str = ""
    type_name: str = ""
    # (field key, what was dropped) — the dry run reports these and points at the
    # Fields tab row to fix.
    dropped: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class LinkDraft:
    target_jira_key: str
    link_type: str
    inward: bool


@dataclass
class CommentDraft:
    jira_id: str
    body: str
    author_id: uuid.UUID | None
    created: str | None


@dataclass
class WorklogDraft:
    jira_id: str
    time_spent: str  # Jira duration text ("3h 30m") — parsed by the timelogging service
    worked_on: str | None  # YYYY-MM-DD, the day the work is booked to
    note: str
    author_id: uuid.UUID | None
    created: str | None


def build(
    payload: dict,
    mappings: PlanMappings,
    vocab: Vocab,
    catalog_types: dict[str, FieldType],
) -> ItemDraft:
    """One cached issue → a fully resolved draft."""
    fields = payload.get("fields") or {}
    key = payload.get("key", "")
    # `issuemap` still decodes Jira's value shapes; only the JUDGEMENTS move here.
    legacy = issuemap.map_issue(
        payload,
        mappings.fields,
        catalog_types,
        epic_link_field=vocab.epic_link_field_id or None,
        sprint_field_ids=vocab.sprint_field_ids,
    )

    type_name = _named(fields.get("issuetype"))
    status_name = _named(fields.get("status"))
    draft = ItemDraft(
        jira_key=key,
        number=issuemap.jira_number(key),
        title=legacy.title,
        description=legacy.description,
        kind=vocab.kind_by_type.get(type_name, ItemKind.ISSUE),
        type_id=vocab.type_id_by_type.get(type_name),
        state_id=vocab.state_id_by_status.get(status_name),
        state_category=vocab.category_by_status.get(status_name, StateCategory.TODO),
        priority=vocab.priority_by_name.get(_named(fields.get("priority")), Priority.NORMAL),
        assignee_id=_person_id(fields.get("assignee"), vocab),
        reporter_id=_person_id(fields.get("reporter"), vocab),
        created=legacy.created,
        updated=legacy.updated,
        labels=list(legacy.labels),
        custom_fields=dict(legacy.custom_fields),
        parent_jira_key=legacy.parent_jira_key or "",
        epic_jira_key=legacy.epic_jira_key or "",
        estimate_points=legacy.estimate_points,
        start_date=legacy.start_date,
        target_date=legacy.target_date,
    )
    draft.status_name = status_name
    draft.type_name = type_name
    _drop_unaccepted_values(draft, vocab)

    # Sprints and versions the plan keeps.
    draft.sprint_names = [s.name for s in legacy.sprints if s.name in vocab.cycle_names]
    draft.version_names = [
        name
        for version in fields.get("fixVersions") or []
        if (name := _named(version)) in vocab.version_names
    ]
    _apply_components(draft, fields, vocab)

    for email in legacy.native_watcher_emails:
        # The plan resolves the watchers it knows and quietly leaves the rest — a
        # watcher is not worth failing an issue over.
        if (resolved := _author_id("", email, vocab)) is not None:
            draft.watcher_ids.append(resolved)

    draft.links = [
        LinkDraft(
            target_jira_key=link.target_key.upper(),
            link_type=vocab.link_key_by_name.get(link.jira_type_name, link.link_type),
            inward=link.inward,
        )
        for link in legacy.links
        if link.jira_type_name not in vocab.ignored_links
    ]
    draft.comments = [
        CommentDraft(
            jira_id=comment.jira_id,
            body=comment.body,
            author_id=_author_id(comment.author_key, comment.author_email, vocab),
            created=comment.created,
        )
        for comment in legacy.comments
    ]
    draft.worklogs = [
        WorklogDraft(
            jira_id=worklog.jira_id,
            time_spent=worklog.time_spent,
            worked_on=worklog.worked_on,
            note=worklog.note,
            author_id=_author_id(worklog.author_key, worklog.author_email, vocab),
            created=worklog.created,
        )
        for worklog in legacy.worklogs
    ]
    draft.attachment_ids = [
        str(a.get("id")) for a in fields.get("attachment") or [] if a.get("id")
    ]
    return draft


def _drop_unaccepted_values(draft: ItemDraft, vocab: Vocab) -> None:
    """Remove select values the target field will not accept.

    Mapping into an EXISTING select whose option list predates this import is
    routine — and Radd rejects an out-of-options value for the whole item. Seven
    real issues were lost to a single unlisted `domain` value before this existed.
    The value goes, the issue stays, and the dry run names both.
    """
    for key, allowed in vocab.field_options.items():
        if key not in draft.custom_fields or not allowed:
            continue
        value = draft.custom_fields[key]
        if isinstance(value, list):
            kept = [v for v in value if v in allowed]
            dropped = [v for v in value if v not in allowed]
            if dropped:
                draft.custom_fields[key] = kept
                draft.dropped.extend((key, str(v)) for v in dropped)
        elif value is not None and value not in allowed:
            draft.custom_fields.pop(key)
            draft.dropped.append((key, str(value)))


def _apply_components(draft: ItemDraft, fields: dict, vocab: Vocab) -> None:
    names = [name for c in fields.get("components") or [] if (name := _named(c))]
    if not names or vocab.component_action is ComponentAction.IGNORE:
        return
    if vocab.component_action is ComponentAction.LABEL:
        draft.labels = list(dict.fromkeys([*draft.labels, *names]))
    elif vocab.component_field_key:
        draft.custom_fields[vocab.component_field_key] = names


def _person_id(raw: dict | None, vocab: Vocab) -> uuid.UUID | None:
    """Resolve through the plan's USERS table, keyed on Jira's stable username.

    Keyed on the username rather than the email because Jira often exposes no
    address — which is exactly the case spec 90 answered by inventing one.
    """
    if not raw:
        return None
    key = (raw.get("name") or raw.get("key") or raw.get("accountId") or "").strip()
    if not key or key in vocab.skipped_users:
        return None
    return vocab.user_id_by_key.get(key)


def _author_id(key: str, email: str | None, vocab: Vocab) -> uuid.UUID | None:
    """A comment/worklog author, by Jira username first and address second.

    Both routes end at the same row of the plan's Users table, so an author is
    never credited to whoever ran the import — the failure spec 90 had, where an
    unresolved author silently fell through to the importing admin.
    """
    if key:
        if key in vocab.skipped_users:
            return None
        if (resolved := vocab.user_id_by_key.get(key)) is not None:
            return resolved
    if email and (resolved := vocab.user_id_by_email.get(email.strip().lower())):
        return resolved
    return None


def _named(raw: object) -> str:
    if isinstance(raw, dict):
        return str(raw.get("name") or raw.get("value") or "").strip()
    return str(raw).strip() if raw else ""
