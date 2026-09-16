"""Vocabulary for the Jira import connector (spec 90).

Every value that names a behaviour, stage, or mapping decision is an enum here —
the wizard, the client, and the run worker all speak this, never string literals.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class JiraEvent(StrEnum):
    """Spec 123: connection administration, audited with a diff; the credential
    appears only as "changed". Not triggers."""

    CONNECTION_CREATED = "jira_connection.created"
    CONNECTION_UPDATED = "jira_connection.updated"
    CONNECTION_DELETED = "jira_connection.deleted"


class JiraEntity(StrEnum):
    JIRA = "jira"  # connection-level errors (unreachable, unauthorized)
    CONNECTION = "jira_connection"
    SNAPSHOT = "jira_snapshot"
    IMPORT_PLAN = "jira_import_plan"
    IMPORT_RUN = "jira_import_run"


class SnapshotStage(StrEnum):
    """Where a download is (spec 100). The order IS the pipeline.

    CATALOGS first because everything downstream identifies fields by Jira's own
    schema keys, and because knowing the instance's issue types / statuses /
    priorities / link types up front is what lets the mapping step present real
    vocabularies instead of guesses scraped from a sample.

    COMMENTS/WORKLOGS/HISTORY are BACKFILL passes: `/search` inlines only the
    first page of each per issue and reports the true count alongside. Spec 90
    took the inline list at face value, so an issue with 87 comments imported 20
    and nothing said so.
    """

    PENDING = "pending"
    CATALOGS = "catalogs"  # /field, /issuetype, /status, /priority, /issueLinkType, …
    ISSUES = "issues"  # page the JQL, one row per issue
    COMMENTS = "comments"  # backfill any truncated comment list
    WORKLOGS = "worklogs"  # backfill any truncated worklog list
    HISTORY = "history"  # backfill any truncated changelog
    ATTACHMENTS = "attachments"  # download binaries into the attachment store
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


# Stages that mean the download is over, whatever the outcome.
TERMINAL_SNAPSHOT_STAGES: frozenset[SnapshotStage] = frozenset(
    {SnapshotStage.DONE, SnapshotStage.FAILED, SnapshotStage.CANCELED}
)


class SnapshotCatalog(StrEnum):
    """Keys inside a snapshot's `catalogs` blob — the instance's own vocabularies,
    captured once at download time so every later step is offline and repeatable."""

    FIELDS = "fields"  # {id: {name, schema_type, schema_items, schema_key, is_custom}}
    OPTION_SETS = "option_sets"  # {field_id: [configured option, …]}
    ISSUE_TYPES = "issue_types"
    STATUSES = "statuses"
    PRIORITIES = "priorities"
    LINK_TYPES = "link_types"
    RESOLUTIONS = "resolutions"
    VERSIONS = "versions"  # the project's fix versions
    COMPONENTS = "components"


class RunKind(StrEnum):
    """What a run over a snapshot is doing (spec 100). All three share one row and
    one progress surface because they are the same pipeline."""

    DRY_RUN = "dry_run"  # build every operation, write nothing, report
    IMPORT = "import"  # build the same operations and apply them
    ROLLBACK = "rollback"  # walk the ledger backwards


class RunStage(StrEnum):
    """The import pipeline, in order. ITEMS first with Jira numbers preserved, so
    every key is addressable before anything references it; PARENTS and LINKS only
    once every issue exists."""

    PENDING = "pending"
    PROVISION = "provision"  # project, fields, states, types, link types, users
    ITEMS = "items"
    PARENTS = "parents"
    LINKS = "links"
    COMMENTS = "comments"
    WORKLOGS = "worklogs"
    ATTACHMENTS = "attachments"
    HISTORY = "history"
    RELINK = "relink"  # resolve anything now importable
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_RUN_STAGES: frozenset[RunStage] = frozenset(
    {RunStage.DONE, RunStage.FAILED, RunStage.CANCELED}
)


class LedgerEntity(StrEnum):
    """What the provenance ledger can hold — everything an import creates, so
    rollback can undo all of it in reverse dependency order."""

    PROJECT = "project"
    FIELD = "field"
    STATE = "state"
    ISSUE_TYPE = "issue_type"
    LINK_TYPE = "link_type"
    USER = "user"
    CYCLE = "cycle"
    RELEASE = "release"
    TEAM = "team"
    ITEM = "item"
    COMMENT = "comment"
    WORKLOG = "worklog"
    ITEM_LINK = "item_link"
    WEB_LINK = "web_link"
    ATTACHMENT = "attachment"


class LedgerAction(StrEnum):
    CREATED = "created"  # rollback deletes it
    UPDATED = "updated"  # rollback restores `before`


class PendingRefKind(StrEnum):
    PARENT = "parent"
    LINK = "link"


class ProblemKind(StrEnum):
    """Why something did not work (spec 100).

    Structured, not a formatted string: the UI groups by (kind, message) and lists
    the affected subjects underneath, which is what turns "50 errors, truncated to
    20" into "12 issues reference a field that no longer exists: DEV-1, DEV-7, …".
    """

    JIRA_UNREACHABLE = "jira_unreachable"
    COMMENTS_FETCH = "comments_fetch"
    WORKLOGS_FETCH = "worklogs_fetch"
    HISTORY_FETCH = "history_fetch"
    ATTACHMENT_FETCH = "attachment_fetch"
    ATTACHMENT_TOO_LARGE = "attachment_too_large"
    CATALOG_FETCH = "catalog_fetch"
    # Import-side (spec 100). Every one names the issue it happened to, so the UI
    # groups by cause and lists exactly which tickets are affected.
    PROVISION_FAILED = "provision_failed"
    ITEM_FAILED = "item_failed"
    PARENT_INCOMPATIBLE = "parent_incompatible"
    LINK_UNRESOLVED = "link_unresolved"
    WORKLOG_FAILED = "worklog_failed"
    COMMENT_RESTRICTED = "comment_restricted"
    USER_UNRESOLVED = "user_unresolved"
    VALUE_DROPPED = "value_dropped"
    PERMISSION = "permission"
    ROLLBACK_BLOCKED = "rollback_blocked"


@dataclass(frozen=True)
class Problem:
    """One thing that went wrong, with the subject it went wrong FOR — and, where
    a mapping decision caused it, WHICH decision.

    `section` + `mapping_key` are what turn "6 issues skipped" into "the status
    'Needs Discussion' has no state — fix it in Statuses". Without them the run
    report says something failed and leaves you to guess which of nine mapping
    tables to go and look at.
    """

    kind: ProblemKind
    message: str  # the reason, in plain words
    subject: str = ""  # the Jira key / field id / user this concerns
    detail: str = ""  # the raw error, for the expandable row
    section: str = ""  # the mapping tab to fix it in ("fields", "statuses", …)
    mapping_key: str = ""  # the row within that tab (a Jira status name, a field key)

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "subject": self.subject,
            "detail": self.detail,
            "section": self.section,
            "mapping_key": self.mapping_key,
        }


class JiraAuthMode(StrEnum):
    """How Radd authenticates to a Jira instance (spec 100).

    Jira DC accepts both. A PAT is the idiom and a read-only one is enough; basic
    auth is the fallback for instances where tokens are disabled."""

    PAT = "pat"  # personal access token, sent as `Authorization: Bearer`
    BASIC = "basic"  # username + password


class JiraConnectionSource(StrEnum):
    """Where a connection row came from (spec 100) — display only.

    An ENV-seeded row is a normal editable connection, not a locked one: the whole
    point of moving connections into the database is that fixing a typo'd URL must
    not need a redeploy. The source is recorded so the UI can say where it came
    from, and so seeding knows never to re-create a row the admin deleted."""

    ENV = "env"  # seeded once from RADD_JIRA_* at startup
    USER = "user"  # created through the API


class FieldAction(StrEnum):
    """What the wizard decided to do with one inbound Jira field (spec 90)."""

    IGNORE = "ignore"  # drop it — not worth importing
    MAP = "map"  # write it into an EXISTING Radd custom field (by key)
    CREATE = "create"  # make a new Radd custom field, then write into it
    NATIVE = "native"  # route its value into a native Radd feature (BuiltinTarget)
    BUILTIN = "builtin"  # the Jira field IS a standard column (summary/status/…), auto-handled


class BuiltinTarget(StrEnum):
    """A native Radd concept a Jira field's VALUE can be routed into (spec 90).

    Distinct from a custom field: e.g. a 'Domain' select → a TEAM assignment, a
    'Watchers' user field → WATCHERS, an 'Epic Link' → the PARENT relationship
    (resolved in the second pass, so the epic need not be imported first). The
    standard Jira fields (assignee/priority/labels/dates) are ALSO offered here so
    a non-standard field can feed them.
    """

    TEAM = "team"  # value = a team name → find-or-create a team, assign it
    STATUS = "status"  # value = a Jira status → find-or-create a workflow state
    WATCHERS = "watchers"  # value = user(s) → add as watchers
    PARENT = "parent"  # value = a Jira issue key → parent link (second pass)
    ASSIGNEE = "assignee"  # value = a user → assignee
    LABELS = "labels"  # value(s) → labels
    CYCLE = "cycle"  # value = a name → find-or-create a cycle
    PRIORITY = "priority"  # value = a priority name → item priority
    START_DATE = "start_date"  # value = a date
    TARGET_DATE = "target_date"  # value = a date
    # Jira ships story points as a CUSTOM field ("Story Points"), so without this
    # it could only become a generic number field — never Radd's first-class
    # `estimate_points` (spec 70), which is what velocity, burndown and SLQ
    # `points` actually read.
    POINTS = "points"  # value = a number → estimate_points


# Native targets whose per-value translation (`value_map`) names an ENTITY to
# find-or-create (a team, a workflow state) rather than a scalar value.
ENTITY_VALUE_TARGETS: frozenset[BuiltinTarget] = frozenset(
    {BuiltinTarget.TEAM, BuiltinTarget.STATUS}
)


class VocabAction(StrEnum):
    """What to do with one value of a Jira vocabulary (spec 100).

    The same three choices for issue types, statuses, link types, sprints and
    versions — so the mapping tables read the same way whatever they map.
    """

    MAP = "map"  # use an existing Radd entity
    CREATE = "create"  # provision a new one
    IGNORE = "ignore"  # drop it (the default for anything unused)


class ComponentAction(StrEnum):
    """Radd has no component concept, so a Jira component needs a real decision."""

    LABEL = "label"  # becomes a label on the item
    FIELD = "field"  # written into a custom field
    IGNORE = "ignore"


class UserAction(StrEnum):
    """What to do about a person Jira names that Radd may not know (spec 100).

    Spec 90 had exactly one behaviour — invent an address on a hardcoded company
    domain and create an account — and no way to say otherwise.
    """

    MATCH = "match"  # an existing Radd user (auto-matched or picked)
    PLACEHOLDER = "placeholder"  # create a password-less account for them
    FALLBACK = "fallback"  # attribute their work to one nominated user
    SKIP = "skip"  # leave their work unattributed


class FieldScope(StrEnum):
    """Where a CREATE-mapped custom field lives (spec 90). Global fields are
    shared by every project; project fields belong to the import's target."""

    GLOBAL = "global"
    PROJECT = "project"


class FieldBand(StrEnum):
    """How much attention an inbound Jira field deserves (spec 100).

    One ordered band per field replaces spec 90's two loose booleans
    (`is_builtin` + `likely_noise`), which could not express "unused" at all — so
    a field no issue has ever filled in scored as ordinary data and sat at the top
    of the mapping grid. On a real instance that is most of the catalog: 337
    fields, of which a couple of dozen carry anything.

    Only IN_USE is shown expanded. The rest are collapsed AND default to `ignore`,
    so the mapping step opens on the handful of fields that actually matter — and
    nothing is hidden without a reason you can read and overrule.
    """

    IN_USE = "in_use"  # has values, and is real ticket data
    NOISE = "noise"  # has values, but is machinery or an org-wide default
    UNUSED = "unused"  # no issue carries a value — nothing to import
    BUILTIN = "builtin"  # a native Jira column, handled without a mapping


# Display order in the mapping grid: what matters first.
FIELD_BAND_ORDER: dict[FieldBand, int] = {
    FieldBand.IN_USE: 0,
    FieldBand.NOISE: 1,
    FieldBand.UNUSED: 2,
    FieldBand.BUILTIN: 3,
}

# Bands that default to `ignore` — "hidden and ignored unless you say otherwise".
IGNORED_BANDS: frozenset[FieldBand] = frozenset({FieldBand.NOISE, FieldBand.UNUSED})


class InferredType(StrEnum):
    """What a sampled Jira field looks like (spec 90) — the guess the wizard
    shows and the default create-type it proposes. Deliberately coarse: the admin
    overrides it when mapping."""

    TEXT = "text"  # free text / rich text
    SELECT = "select"  # a small set of scalar values → a Radd select field
    MULTI_SELECT = "multi_select"  # array of scalar values
    NUMBER = "number"
    DATE = "date"
    USER = "user"  # a Jira user object (assignee-like)
    UNKNOWN = "unknown"


# Native Jira field ids that never map to a Radd custom field — they drive
# built-in columns or are pure noise. The wizard hides them from the mapping grid.
BUILTIN_JIRA_FIELDS: frozenset[str] = frozenset(
    {
        "summary", "description", "issuetype", "status", "priority", "assignee",
        "reporter", "creator", "created", "updated", "resolutiondate", "duedate",
        "labels", "parent", "subtasks", "issuelinks", "comment", "worklog",
        "project", "timespent", "timeoriginalestimate", "timeestimate", "attachment",
        "aggregatetimespent", "aggregatetimeoriginalestimate", "workratio", "votes",
        "watches", "thumbnail", "lastViewed", "statuscategorychangedate",
    }
)

# Spec 100 DELETED the two lists that used to live here — a frozenset of literal
# `customfield_*` ids and a frozenset of English field names. Both encoded one
# Jira instance: the ids mean something different (or nothing) elsewhere, and the
# names only match an English-language Jira. A live check on found the
# id list had even gone stale against its OWN instance — `customfield_51604` was
# no longer there. Both are replaced by `schemakeys`, which identifies fields by
# Jira's stable `schema.custom` type key, plus the dominance heuristic below.

# When the single most common value covers at least this fraction of populated
# issues, the field is an org-wide default (HR/travel junk), not real ticket data.
# This one IS instance-independent: it measures the data, not a name.
DOMINANCE_NOISE = 0.85
DOMINANCE_NOISE_REASON = "nearly every issue has the same value — an org-wide default"


@dataclass(frozen=True)
class JiraCreds:
    """Everything needed to talk to one Jira instance (spec 100).

    Deliberately a plain frozen dataclass rather than the ORM row: every REST call
    runs in a worker thread (`asyncio.to_thread`), and handing a SQLAlchemy object
    across that boundary invites a lazy load on a session that belongs to another
    greenlet. Resolve the connection in async code, pass this into the thread.
    """

    base_url: str  # e.g. https://jira.example.com (no trailing /rest)
    auth_mode: JiraAuthMode
    credential: str = ""  # PAT, or the password in basic mode
    username: str = ""  # basic mode only
    verify_ssl: bool = True
    timeout_seconds: float = 30.0

    @property
    def usable(self) -> bool:
        """A base URL plus the credential its mode requires."""
        if not self.base_url or not self.credential:
            return False
        return self.auth_mode is not JiraAuthMode.BASIC or bool(self.username)


@dataclass(frozen=True)
class JiraProject:
    """One project from Jira's /project (spec 90)."""

    key: str
    name: str
    id: str
    project_type: str = ""


@dataclass
class InferredField:
    """One field seen while sampling a JQL result set (spec 90)."""

    jira_id: str  # e.g. "customfield_10002" or "priority"
    name: str  # human label from Jira's field catalog
    inferred_type: InferredType
    populated: int  # sample issues where it had a value
    sample_count: int  # sample issues examined
    is_builtin: bool  # feeds a native column → not a mapping candidate
    distinct_count: int = 0  # distinct scalar values across the sample
    dominant_ratio: float = 0.0  # share of the single most common value (1.0 = constant)
    samples: list[str] = field(default_factory=list)  # a few example rendered values
    distinct_values: list[str] | None = None  # for SELECT-like fields: the option set
    # Spec 100. `schema_key` is Jira's own `schema.custom` — the same on every
    # instance — which is what identifies Sprint/Epic Link/rank without hardcoding
    # ids. `band` decides whether the field is shown or collapsed-and-ignored, and
    # `band_reason` is shown verbatim so a collapsed field can be argued with.
    schema_key: str = ""
    band: FieldBand = FieldBand.IN_USE
    band_reason: str = ""
    native_target: "BuiltinTarget | None" = None  # the concept this field suggests

    @property
    def ignored_by_default(self) -> bool:
        return self.band in IGNORED_BANDS

    @property
    def populate_rate(self) -> float:
        return (self.populated / self.sample_count) if self.sample_count else 0.0
