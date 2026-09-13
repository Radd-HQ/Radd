"""Prompt assembly (pure, unit-tested).

The NL->SLQ system prompt transcribes the FROZEN spec-10 grammar (kept in sync
with the cheat sheet in `web/src/lib/slq.ts` and `items/slq/catalog.py`) and
appends the instance's live field registry. Summarize/similar prompts build
compact digests from values the caller's RBAC already filtered.
"""

from collections.abc import Sequence
from typing import Any

from radd.modules.fields.types import FieldType
from radd.modules.workflow.types import StateCategory
from radd.modules.ai.types import STATE_WORDS, SlqDialect

# --- NL -> SLQ ---

# Spec-10 grammar, frozen. Builtin fields + operators + value forms mirror the
# frontend cheat sheet (SLQ_BUILTIN_FIELDS / SLQ_OPERATORS / SLQ_VALUE_NOTES)
# plus the catalog-only fields (cycle/release/start/target/blocks/blocked).
SLQ_GRAMMAR = """\
SLQ is a JQL-like text query language over work items.

Builtin fields (field names are case-sensitive):
- project: project key — `project = TD`
- state: state name — `state != Done`
- category: state category (todo | in_progress | done | …) — `category IN (todo, in_progress)`
- kind: epic | issue | subtask — `kind = epic`
- priority: low | normal | high | blocker — `priority IN (high, blocker)`
- assignee: email | me | none — `assignee = me`
- reporter: email | me | none — `reporter = me`
- team: team name | none — `team = "FX"`
- label: label name (= has, != lacks, IN = has any) — `label IN (urgent, blocked)`
- title: text (~ = contains, case-insensitive) — `title ~ "render farm"`
- key: item key — `key = TD-12`
- parent: parent key | none — `parent = TD-3`
- epic: the epic an item belongs to — an EPIC BELONGS TO ITSELF, so `epic = TD-3` returns TD-3 plus its issues and subtasks; `epic IS EMPTY` = work under no epic (epics are never in that bucket — use `kind = epic` for those)
- epic.state / epic.category / epic.assignee / epic.priority: that epic's own attributes, matching the epic itself as well as its children — `epic.state = "In Progress"` (filter-only, not sortable)
- parent.state / parent.category / parent.assignee / parent.priority: the DIRECT parent's attributes; unlike `epic.*` these never match the item itself
- number: item number — `number > 100`
- created: YYYY-MM-DD — `created >= 2026-01-01`
- updated: YYYY-MM-DD — `updated < 2026-07-01`
- cycle: cycle name | none — `cycle = "Sprint 4"`
- release: release version | none — `release IS EMPTY`
- start: start date, YYYY-MM-DD — `start >= 2026-01-01`
- target: target date, YYYY-MM-DD — `target <= 2026-03-31`
- flagged: true | false — `flagged = true`
- starred: true | false (the current user's personal stars) — `starred = true`
- blocks / blocked: item key, or IS [NOT] EMPTY — `blocked IS NOT EMPTY`

Operators:
- =  != : equals / not equals
- ~ : contains, case-insensitive (title and text fields)
- >  <  >=  <= : compare numbers and YYYY-MM-DD dates
- IN (a, b)  /  NOT IN (a, b) : any of / none of the listed values
- IS EMPTY  /  IS NOT EMPTY : value unset / set
- AND  OR  NOT  ( ) : combine conditions — AND binds tighter than OR
- ORDER BY field [ASC|DESC], ... : sort the results (default: created DESC)

Values:
- Bare words need no quotes; use 'single' or "double" quotes for values with spaces.
- Keywords are case-insensitive; field names are case-sensitive.
- me = the current user (assignee/reporter); none = unset relation (same as IS EMPTY).
- != / NOT IN on a relation (assignee, team, type, cycle, release, epic.*, parent.*) also match items where it is unset — `assignee != me` includes the unassigned.

Examples:
- state != Done AND priority IN (high, blocker)
- assignee = me AND category = in_progress
- (team = "FX" OR team = "Comp") AND label = urgent
- assignee IS EMPTY ORDER BY created ASC
- updated >= 2026-01-01 ORDER BY priority DESC, updated DESC
"""

# Operator surface per custom-field type (mirror of slq.ts cfOpsHint / catalog CF_OPS).
_CF_OPS_HINTS: dict[str, str] = {
    FieldType.SELECT: "=  !=  ~  IN",
    FieldType.TEXT: "=  !=  ~  IN",
    FieldType.URL: "=  !=  ~  IN",
    FieldType.MULTI_SELECT: "= (contains)  IN",
    FieldType.NUMBER: "=  !=  >  <  >=  <=",
    FieldType.DURATION: "=  !=  >  <  >=  <=",
    FieldType.DATE: "=  !=  >  <  >=  <=",
    FieldType.BOOLEAN: "= true | false",
}
_CF_OPS_DEFAULT = "=  !="


# The worklog dialect's own surface (spec 98) — everything of the ITEM lives
# behind the `issue.` prefix, so the item grammar below stays the vocabulary.
WORKLOG_GRAMMAR = """\
You are writing for the TIMESHEET: rows are WORKLOGS (time entries), not items.
Bare fields are the worklog's own:
- author (me | none | an email; also IN (...))
- category (work category name), project (project key), note (~ contains text)
- worked_on (a date: YYYY-MM-DD, today, today-3d, today-2w; supports < <= > >=)
- time (a duration: 30m, 2h, 1d; supports < <= > >=)
- issue — three forms: `issue IS EMPTY` (general worklogs with no item),
  `issue = DEV-123` (one item by key), and `issue.<field>` which reaches ANY
  item field from the grammar below: issue.state != Done, issue.assignee = me,
  issue.label = urgent, issue.priority IN (high, blocker).
CRITICAL: item fields are ONLY valid behind `issue.` here — write
`issue.state != Done`, NEVER a bare `state != Done`.
"""


def nl_system_prompt(
    definitions: Sequence[Any],
    dialect: str = "items",
    *,
    issue_types: Sequence[str] = (),
    work_categories: Sequence[str] = (),
    states: Sequence[str] = (),
) -> str:
    """The NL->SLQ system prompt: frozen grammar + the live field registry.

    `definitions` duck-types FieldDefinition (key/name/type/options/ai_visible);
    fields marked ai_visible=False never reach the prompt. `dialect` swaps the
    framing: "worklog" prepends the timesheet surface and prefixes custom keys
    with `issue.` (spec 98 delegation). `issue_types`/`work_categories`/`states`
    are the LIVE small value sets — without them the model maps "bugs" onto the
    generic `kind` instead of the Bug issue type, and writes `state = Fixed`
    on a workflow that has no such state (both seen live; RADD-1140).
    """
    worklog = dialect == SlqDialect.WORKLOG.value
    key_prefix = "issue." if worklog else ""
    lines: list[str] = []
    for definition in definitions:
        if not getattr(definition, "ai_visible", True):
            continue
        hint = _CF_OPS_HINTS.get(str(definition.type), _CF_OPS_DEFAULT)
        options = definition.options or None
        suffix = f"; options: {', '.join(options)}" if options else ""
        lines.append(
            f'- {key_prefix}{definition.key} '
            f'("{definition.name}", {definition.type}; ops: {hint}{suffix})'
        )
    registry = (
        "Custom fields on this tracker (query by key, exactly as listed):\n" + "\n".join(lines)
        if lines
        else "This tracker has no custom fields — use only the builtin fields above."
    )
    if issue_types:
        registry += (
            f"\n\nIssue types on this tracker (the {key_prefix}type field): "
            + ", ".join(issue_types)
            + ". When the user names one of these (bugs, features, …), filter with "
            + f"{key_prefix}type — {key_prefix}kind is ONLY the hierarchy level "
            + "(epic | issue | subtask)."
        )
    if states:
        registry += (
            f"\n\nWorkflow states on this tracker (the {key_prefix}state field, exact names): "
            + ", ".join(states)
            + ". Use "
            + f"{key_prefix}state ONLY for one of these names. Words like "
            + ", ".join(sorted(STATE_WORDS.done))
            + f" mean {key_prefix}category = {StateCategory.DONE.value}; "
            + ", ".join(sorted(STATE_WORDS.not_done))
            + f" mean {key_prefix}category != {StateCategory.DONE.value} — unless the user "
            + "names an actual state from the list."
        )
    if worklog and work_categories:
        registry += (
            "\n\nWork categories (the bare `category` field): " + ", ".join(work_categories) + "."
        )
    if worklog:
        intro = (
            "You translate a natural-language question about logged time into one "
            "worklog SLQ query.\n\n" + WORKLOG_GRAMMAR + "\n"
            "Item fields (use them ONLY with the issue. prefix here):\n"
        )
    else:
        intro = "You translate a natural-language question about work items into one SLQ query.\n\n"
    return (
        intro
        + SLQ_GRAMMAR
        + "\n"
        + registry
        + "\n\n"
        + "Reply with ONLY a JSON object, no prose around it:\n"
        + '{"slq": "<the query>", "explanation": "<one short sentence of what it matches>"}\n'
        + "Use only fields listed above. Prefer the simplest query that answers the question.\n"
        + "For people, states, labels, teams, cycles, releases and types, use the user's "
        + "words verbatim (quoted when multi-word) — NEVER invent emails or guess exact "
        + "record names; values are matched to the real records afterwards."
    )


def nl_user_prompt(question: str, *, today: str = "") -> str:
    """`today` (ISO date) anchors relative language — without it the model
    guesses "this month" from its training data (seen live: 2025-05-01)."""
    prefix = f"Today is {today}. " if today else ""
    return f"{prefix}Question: {question}"


def nl_retry_prompt(question: str, bad_slq: str, error: str) -> str:
    """Second attempt: the server's compile error appended so the model can self-correct."""
    return (
        f"Question: {question}\n\n"
        f"Your previous query failed to compile.\n"
        f"Query: {bad_slq}\n"
        f"Error: {error}\n\n"
        "Return a corrected JSON object in the same format."
    )


# --- summarize ---

SUMMARIZE_SYSTEM = (
    "You summarize a work item from an issue tracker for a colleague taking the work "
    "over. Write a tight hand-off summary in markdown: what it is and why it matters, "
    "where it stands now, notable recent activity, and open questions or next steps. "
    "When a Time tracking section is present, include one line on effort — the total "
    "logged and who spent it. Be concrete, do not invent facts, and stay under about "
    "250 words."
)


def summarize_user_prompt(
    *,
    key: str,
    title: str,
    kind: str,
    state: str,
    priority: str,
    assignee: str | None,
    labels: Sequence[str],
    description: str,
    comments: Sequence[tuple[str, str]],
    history: Sequence[str],
    worklogs: Sequence[str] = (),
) -> str:
    """The item digest: metadata + description + recent comments + change
    history + the time-tracking digest. `worklogs` is empty whenever the
    project doesn't log time — the section then never appears, so the model
    is never told about a facility the instance doesn't use."""
    parts = [
        f"Item {key}: {title}",
        f"Kind: {kind} | State: {state} | Priority: {priority} | "
        f"Assignee: {assignee or 'unassigned'}",
    ]
    if labels:
        parts.append("Labels: " + ", ".join(labels))
    parts.append("\nDescription:\n" + (description.strip() or "(empty)"))
    if comments:
        parts.append(
            "\nRecent comments (oldest first):\n"
            + "\n".join(f"- {author}: {body}" for author, body in comments)
        )
    if history:
        parts.append("\nRecent changes:\n" + "\n".join(f"- {line}" for line in history))
    if worklogs:
        parts.append("\nTime tracking:\n" + "\n".join(f"- {line}" for line in worklogs))
    return "\n".join(parts)


# --- similar / duplicate detection ---

# RELATED issues, not just duplicates: the first prompt said "detect duplicate
# issues ... omit candidates that are clearly unrelated", and models obeyed —
# they kept the literal twin and dropped everything merely related, so "Find
# similar" usually returned one candidate or none.
SIMILAR_SYSTEM = (
    "You rank RELATED issues in a tracker. Given a source issue and candidate "
    "issues, score each candidate from 0 to 1 for how related it is to the source: "
    "1 = the same underlying issue (a duplicate), around 0.8 = same feature or bug "
    "area, around 0.5 = same component or clearly adjacent work, below 0.3 = "
    "unrelated. KEEP related candidates even when they are not duplicates — say in "
    "the reason when one likely IS a duplicate. Omit only clearly unrelated "
    "candidates. Reply with ONLY a JSON array, no prose around it:\n"
    '[{"key": "<item key>", "score": <0..1>, "reason": "<short reason>"}]'
)


def similar_user_prompt(
    *,
    key: str,
    title: str,
    description: str,
    candidates: Sequence[tuple[str, str, str]],
) -> str:
    """Source item + the FTS candidate pool as (key, title, excerpt) rows."""
    lines = [f"Source issue {key}: {title}"]
    if description.strip():
        lines.append(f"Description: {description.strip()}")
    lines.append("\nCandidates:")
    for candidate_key, candidate_title, excerpt in candidates:
        row = f"- {candidate_key}: {candidate_title}"
        if excerpt.strip():
            row += f" — {excerpt.strip()}"
        lines.append(row)
    return "\n".join(lines)
