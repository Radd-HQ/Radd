"""Template variables for automation action params (spec 58b): `{{token}}`
substitution so universal actions (create item / webhook / chat / notify) can
carry the triggering event's facts into their output.

The catalogue is `TOKENS`, served by GET /automations/catalog so the editor can
SHOW what is supported instead of leaving people to guess. It sits next to
`_resolve` deliberately: a documented token that does not resolve renders as a
literal `{{…}}` in somebody's issue title, and a working token nobody documented
is one nobody finds.

Unknown tokens render as-is — visible in the output, debuggable, never an error.

Pure module — tested in tests/test_automation_gates.py and test_automation_arity.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Mapping

from .conditions import EventFacts, _payload_path

#: The token grammar. PUBLIC since spec 120 — the write path scans a whole
#: graph for tokens, and a second regex there would eventually admit something
#: this one does not.
TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")
_TOKEN_RE = TOKEN_RE


@dataclass(frozen=True)
class TokenInfo:
    """One documented token, for the editor's reference panel.

    Served rather than written into the SPA because this list and `_resolve`
    below must not drift: a token documented but unresolved renders as literal
    `{{…}}` in someone's issue title, and an unlisted token that works is one
    nobody finds. They are defined side by side here for exactly that reason.
    """

    token: str
    description: str
    #: Only meaningful when the run has a target item — an itemless event (a
    #: schedule tick, a cycle event) resolves these to nothing, and the panel
    #: says so rather than letting someone build a title around a blank.
    needs_item: bool = False


TOKENS: tuple[TokenInfo, ...] = (
    TokenInfo("{{event_type}}", "The event that fired, e.g. item.updated."),
    TokenInfo("{{actor.name}}", "Who caused the event."),
    TokenInfo("{{actor.email}}", "Their email."),
    TokenInfo("{{actor.id}}", "Their user id."),
    TokenInfo("{{item.key}}", "The target item's key, e.g. TD-42.", needs_item=True),
    TokenInfo("{{item.title}}", "Its title.", needs_item=True),
    TokenInfo("{{item.url}}", "A link to it.", needs_item=True),
    TokenInfo("{{item.state}}", "Its workflow state's name.", needs_item=True),
    TokenInfo("{{item.state_category}}", "That state's category — todo, in_progress, done…", needs_item=True),
    TokenInfo("{{item.priority}}", "low, normal, high or blocker.", needs_item=True),
    TokenInfo("{{item.assignee}}", "The assignee's name; blank when unassigned.", needs_item=True),
    TokenInfo("{{item.reporter}}", "The reporter's name.", needs_item=True),
    TokenInfo("{{item.project}}", "The project's key.", needs_item=True),
    TokenInfo("{{item.type}}", "Its issue type's name.", needs_item=True),
    TokenInfo("{{item.labels}}", "Its labels, comma-separated.", needs_item=True),
    TokenInfo("{{item.id}}", "Its id.", needs_item=True),
    # Set-shaped tokens (RADD-918). An action running ONCE over many items could
    # previously learn only how MANY there were: `{{matched_count}}` was the
    # entire vocabulary, so "post the stale issues to Slack" could say "12" and
    # not which twelve. At item arity these describe the one item, so the same
    # template reads correctly in both modes.
    TokenInfo("{{items.count}}", "How many items this action is acting on."),
    TokenInfo("{{items.keys}}", "Their keys, comma-separated — TD-42, TD-43."),
    TokenInfo("{{items.list}}", "One per line: `TD-42 — the title`. For chat and email bodies."),
    # RADD-1248: the page a comment or page event is about, and the comment
    # itself. Resolved from the payload's refs, so they read the same on a page
    # event (`page` ref) and on a page comment (the same ref, as a subject).
    TokenInfo("{{page.title}}", "The page's title, on a page event or a page comment."),
    TokenInfo("{{page.path}}", "Its readable address inside the space, e.g. onboarding/laptops."),
    TokenInfo("{{page.space}}", "Its space's slug."),
    TokenInfo("{{page.url}}", "A permalink to the page (survives renames and moves)."),
    TokenInfo("{{comment.excerpt}}", "The comment's first 200 characters, on a comment event."),
    TokenInfo("{{comment.visibility}}", "public or internal."),
    TokenInfo("{{comment.parent_id}}", "The thread root's id when the comment is a reply; blank on a root."),
    TokenInfo(
        "{{payload.<path>}}",
        "Anything from the raw event payload, by dotted path — e.g. "
        "{{payload.changes.field}}. Lists join with commas.",
    ),
)


@lru_cache(maxsize=1)
def reserved_roots() -> frozenset[str]:
    """The first segment of every documented token — the words a node may NOT be
    named (spec 120).

    DERIVED from `TOKENS` rather than listed beside it. A hand-kept list would be
    the third copy of this vocabulary (the catalogue, the resolver, the reserved
    set) and the one nobody notices going stale: a root that stopped being
    reserved would let someone name a node `item` and shadow `{{item.key}}` in
    every action of the graph.

    Memoised because `Renderer` asks per TOKEN, and `TOKENS` is a module
    constant — recomputing a twelve-element frozenset inside a render loop over
    200 items is work with no answer attached to it.
    """
    return frozenset(token.token.strip("{} ").split(".", 1)[0] for token in TOKENS)


def _resolve(
    token: str,
    facts: EventFacts,
    item_ctx: dict[str, Any] | None,
    items: list[dict[str, Any]] | None,
) -> str | None:
    if token == "event_type":
        return facts.event_type
    if token.startswith("items."):
        return _resolve_items(token.removeprefix("items."), items)
    if token == "actor.id":
        return facts.actor_id
    if token == "actor.email":
        return facts.actor_email
    if token == "actor.name":
        return facts.actor_name
    if token.startswith("payload."):
        values = _payload_path(facts.payload, token.removeprefix("payload."))
        return ", ".join(str(v) for v in values) if values else None
    if token.startswith("page."):
        return _resolve_page(token.removeprefix("page."), facts.payload)
    if token.startswith("comment."):
        return _resolve_comment(token.removeprefix("comment."), facts.payload)
    if token.startswith("item.") and item_ctx is not None:
        value = item_ctx.get(token.removeprefix("item."))
        return None if value is None else str(value)
    return None


def _resolve_page(field: str, payload: Mapping[str, Any]) -> str | None:
    """The `page` ref the kernel wrote (RADD-1248): on a page event and on a
    page comment alike. The space rides inside the ref, but page events also
    carry a top-level `page_space` ref — either answers `page.space`."""
    page = payload.get("page")
    if not isinstance(page, dict):
        return None
    if field == "space":
        space = page.get("space") or payload.get("page_space")
        return str(space.get("slug")) if isinstance(space, dict) and space.get("slug") else None
    if field == "url":
        from radd.config import settings

        number = page.get("number")
        return f"{settings.app_base_url.rstrip('/')}/pages?pageId={number}" if number else None
    value = page.get(field)
    return None if value is None or isinstance(value, dict) else str(value)


def _resolve_comment(field: str, payload: Mapping[str, Any]) -> str | None:
    """The comment event's own data — `excerpt`, `visibility`, `parent_id`."""
    key = {"parent_id": "parent_comment_id"}.get(field, field)
    if key not in ("excerpt", "visibility", "parent_comment_id"):
        return None
    value = payload.get(key)
    return "" if value is None and key == "parent_comment_id" else (None if value is None else str(value))


def _resolve_items(field: str, items: list[dict[str, Any]] | None) -> str | None:
    """The set-shaped tokens. An empty set resolves to an empty string rather
    than staying verbatim: "0 items" and a blank list are the honest rendering of
    a run that matched nothing, whereas a literal `{{items.keys}}` in the chat
    message reads as a broken automation."""
    if items is None:
        return None
    if field == "count":
        return str(len(items))
    if field == "keys":
        return ", ".join(str(entry.get("key", "")) for entry in items)
    if field == "list":
        return "\n".join(f"{entry.get('key', '')} — {entry.get('title', '')}" for entry in items)
    return None


@dataclass
class Renderer:
    """One action invocation's template resolver (spec 120).

    An OBJECT rather than a function because rendering now has to report on
    itself. The engine needs three answers, and a `str -> str` call can only give
    the first:

    * the text, with tokens substituted;
    * what each token BECAME, so a dry run can show `{{triage.priority}} → high`
      rather than making someone infer it from the result;
    * which VARIABLE tokens found nothing, so the containing action can skip
      with a reason instead of writing a literal `{{triage.priority}}` into
      somebody's issue.

    The last one is scoped deliberately. Every OTHER unresolvable token still
    degrades verbatim, exactly as it has since spec 58b: `{{payload.foo}}` on an
    event that does not carry `foo` is a normal, harmless miss on a shape that
    varies per event, and turning it into a skip would silently disable working
    automations. A variable token is different — it names a node the author
    wired, and if that node did not run, acting anyway is the wrong write.
    """

    facts: EventFacts
    item_ctx: dict[str, Any] | None = None
    items: list[dict[str, Any]] | None = None
    #: The packet's variable bag: node name -> what it produced.
    variables: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    #: `{{token}}` -> what it rendered to, for the dry run.
    resolved: dict[str, str] = field(default_factory=dict)
    #: One sentence per variable token that found nothing, in the order met.
    misses: list[str] = field(default_factory=list)

    def __call__(self, value: Any) -> str:
        def replace(match: re.Match[str]) -> str:
            token = match.group(1)
            found = _resolve(token, self.facts, self.item_ctx, self.items)
            if found is None:
                found = self._from_bag(token)
            if found is None:
                self._record_miss(token, match.group(0))
                return match.group(0)
            self.resolved[match.group(0)] = found
            return found

        return _TOKEN_RE.sub(replace, str(value))

    def line(self, value: Any) -> str:
        """Render, then collapse every run of whitespace to one space.

        For a param that names a THING or becomes a HEADER, never for a body.
        The failure this exists for is silent and total: `EmailMessage` under the
        default policy REFUSES a header containing a newline, so a rendered
        `send_email` subject carrying one raises inside the transport — the dry
        run says "Would apply", the real run logs a crash, and no mail is ever
        sent. Model output is exactly where a stray newline comes from.

        Collapsing is also the right answer for the by-name lookups: a value that
        came back as "In\nProgress" should match the state called "In Progress",
        and a literal someone typed has no whitespace runs to lose.
        """
        return " ".join(self(value).split())

    def _from_bag(self, token: str) -> str | None:
        root, dot, name = token.partition(".")
        if not dot or root in reserved_roots():
            return None
        values = self.variables.get(root)
        return None if values is None else values.get(name)

    def _record_miss(self, token: str, literal: str) -> None:
        root, dot, name = token.partition(".")
        if not dot or root in reserved_roots():
            return  # a documented token that had nothing to say — verbatim, as always
        values = self.variables.get(root)
        if values is None:
            self.misses.append(
                f"{literal} — no node named {root!r} produced anything on this branch"
            )
            return
        made = ", ".join(sorted(values)) or "nothing"
        self.misses.append(f"{literal} — {root!r} produced {made}, not {name!r}")


def render_template(
    text: str,
    facts: EventFacts,
    item_ctx: dict[str, Any] | None = None,
    items: list[dict[str, Any]] | None = None,
    variables: Mapping[str, Mapping[str, str]] | None = None,
) -> str:
    """Substitute `{{token}}` occurrences; unresolvable tokens stay verbatim.

    The one-shot form, kept because most callers want only the text. Anything
    that has to REPORT on the rendering builds a `Renderer` and keeps it."""
    return Renderer(facts, item_ctx, items, variables or {})(text)
