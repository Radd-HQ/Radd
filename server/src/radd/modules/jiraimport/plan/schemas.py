"""The import plan's wire + stored shapes (spec 100).

A plan is one explicit decision per inbound *thing* — every Jira field, and every
value of every Jira vocabulary. Spec 90 mapped fields only; everything else was a
hardcoded English lookup table (`PRIORITY_MAP`, `CATEGORY_MAP`, `LINK_TYPE_MAP`,
`"epic" in name`), which is what tied it to one instance and left the admin unable
to correct a single wrong guess.

Every entry carries its snapshot `count`. That is what drives "hidden and ignored
unless used": a value with count 0 is real (the instance allows it) but absent
from this project, so it collapses and defaults to ignore, with the reason shown.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from radd.apitypes import UtcDatetime
from radd.modules.items.enums import ItemKind, Priority
from radd.modules.workflow.types import StateCategory

from ..schemas import FieldMappingEntry
from ..types import ComponentAction, UserAction, VocabAction


class VocabMapping(BaseModel):
    """Common head of every vocabulary row: the Jira value and how much it is used."""

    jira: str = Field(min_length=1, max_length=200)
    count: int = 0  # issues in the snapshot using it; 0 = hidden + ignored

    @property
    def unused(self) -> bool:
        return self.count == 0


class IssueTypeMapping(VocabMapping):
    """A Jira issue type → Radd's TWO orthogonal axes.

    Spec 90 collapsed this to `"epic" in name` / `"sub" in name`, so "Initiative",
    "Milestone", "Sous-tâche" and every renamed type became a plain issue. Both
    axes are now explicit: `kind` is the hierarchy (epic ← issue ← subtask) and
    `type_name` is the spec-51 classification chip.
    """

    kind: ItemKind = ItemKind.ISSUE
    action: VocabAction = VocabAction.CREATE  # create/map/ignore the Radd issue type
    type_name: str = Field(default="", max_length=100)


class StatusMapping(VocabMapping):
    """A Jira status → a Radd workflow state + its category.

    The category is what analytics, boards and rollover key off, and spec 90 could
    only reach it through an English `CATEGORY_MAP` plus a literal test for
    "cancelled"/"canceled" — so "Rejected", "Won't Do" and "Abandoned" all landed
    in `todo`. Jira's own `statusCategory.key` seeds the suggestion; the admin has
    the final say, which is the only way to express "Rejected means canceled".
    """

    action: VocabAction = VocabAction.CREATE
    state_name: str = Field(default="", max_length=100)
    category: StateCategory = StateCategory.TODO


class PriorityMapping(VocabMapping):
    """A Jira priority → one of Radd's four. Replaces a fixed English table that
    silently sent anything unrecognised — P1, Urgent, Showstopper — to `normal`."""

    priority: Priority = Priority.NORMAL


class LinkTypeMapping(VocabMapping):
    """A Jira issue-link type → a Radd link type (spec 91 makes these definable).
    Spec 90 knew three names and defaulted everything else to `relates`."""

    action: VocabAction = VocabAction.MAP
    key: str = Field(default="", max_length=30)
    outward_name: str = Field(default="", max_length=60)  # create only
    inward_name: str = Field(default="", max_length=60)


class UserMapping(BaseModel):
    """One person Jira names, and what to do about them.

    Identity is Jira's username/key, NOT an email: Jira frequently exposes no
    address, and spec 90's answer was to synthesize one on a hardcoded company
    domain and write it into a real `users` row.
    """

    jira_key: str = Field(min_length=1, max_length=200)
    display_name: str = Field(default="", max_length=200)
    jira_email: str = Field(default="", max_length=320)  # only if Jira exposed one
    count: int = 0
    roles: list[str] = Field(default_factory=list)
    action: UserAction = UserAction.PLACEHOLDER
    # match/fallback: the existing Radd user this person IS.
    user_id: uuid.UUID | None = None
    # placeholder: the address the new account gets. Shown before anything is
    # created, so an invented domain can never be a surprise.
    placeholder_email: str = Field(default="", max_length=320)
    match_reason: str = Field(default="", max_length=200)
    # The matched Radd account is deactivated (a leaver). Their historical
    # attribution is still imported — an import restates history rather than
    # making a new assignment — but it should be visible, not a surprise.
    matched_inactive: bool = False


class SprintMapping(VocabMapping):
    action: VocabAction = VocabAction.CREATE
    cycle_id: uuid.UUID | None = None
    # Carried from the Jira bean so a CLOSED sprint imports as a COMPLETED cycle
    # rather than a dateless draft.
    state: str = ""
    start_date: str = ""
    end_date: str = ""
    complete_date: str = ""


class VersionMapping(VocabMapping):
    """A Jira fix version → a Radd release. Not imported at all before spec 100."""

    action: VocabAction = VocabAction.CREATE
    release_id: uuid.UUID | None = None


class ComponentMapping(VocabMapping):
    """A Jira component → a label, a custom field value, or nothing. Radd has no
    component concept, so this is a genuine choice rather than a default."""

    action: ComponentAction = ComponentAction.LABEL
    target_key: str = Field(default="", max_length=50)  # field action only


class PlanOptions(BaseModel):
    """How the import should behave — the "ask me, don't assume" surface."""

    # Imported work must not notify anyone or trigger automations (spec 100).
    quiet: bool = True
    import_comments: bool = True
    import_worklogs: bool = True
    import_attachments: bool = True
    import_history: bool = True
    # Domain for synthesizing an address Jira did not expose. Blank = derived from
    # the connection's host; shown on the Users step before anything is created.
    placeholder_email_domain: str = Field(default="", max_length=200)


class PlanMappings(BaseModel):
    """Every decision, in one document. Read and written whole, so a JSONB column
    beats nine child tables."""

    fields: list[FieldMappingEntry] = Field(default_factory=list, max_length=1000)
    issue_types: list[IssueTypeMapping] = Field(default_factory=list, max_length=500)
    statuses: list[StatusMapping] = Field(default_factory=list, max_length=500)
    priorities: list[PriorityMapping] = Field(default_factory=list, max_length=100)
    link_types: list[LinkTypeMapping] = Field(default_factory=list, max_length=100)
    users: list[UserMapping] = Field(default_factory=list, max_length=5000)
    sprints: list[SprintMapping] = Field(default_factory=list, max_length=2000)
    versions: list[VersionMapping] = Field(default_factory=list, max_length=1000)
    components: list[ComponentMapping] = Field(default_factory=list, max_length=2000)


class PlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    snapshot_id: uuid.UUID
    radd_project_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9]{0,9}$")
    radd_project_name: str = Field(min_length=1, max_length=200)


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    radd_project_key: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9]{0,9}$")
    radd_project_name: str | None = Field(default=None, min_length=1, max_length=200)
    mappings: PlanMappings | None = None
    options: PlanOptions | None = None


class PlanProblem(BaseModel):
    """A reason the plan cannot run, pointing at the row that has to change."""

    section: str  # "fields" | "statuses" | "users" | …
    subject: str  # the Jira value / field id
    message: str


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    snapshot_id: uuid.UUID
    radd_project_id: uuid.UUID | None
    radd_project_key: str
    radd_project_name: str
    mappings: PlanMappings
    options: PlanOptions
    provisioned_at: UtcDatetime | None
    created_at: UtcDatetime


class PlanValidation(BaseModel):
    ok: bool
    problems: list[PlanProblem] = Field(default_factory=list)
