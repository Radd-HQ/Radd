"""`{{token}}` substitution in automation params (spec 58b). `TOKENS` is served
by GET /automations/catalog and sits next to `_resolve` so the documented and
the working vocabularies cannot drift. Unknown tokens render verbatim. Pure."""

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


@dataclass(frozen=True)
class TokenInfo:
    """One documented token, for the editor's reference panel."""

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
    # Set-shaped tokens (RADD-918): at item arity they describe the one item.
    TokenInfo("{{items.count}}", "How many items this action is acting on."),
    TokenInfo("{{items.keys}}", "Their keys, comma-separated — TD-42, TD-43."),
    TokenInfo("{{items.list}}", "One per line: `TD-42 — the title`. For chat and email bodies."),
    TokenInfo(
        "{{payload.<path>}}",
        "Anything from the raw event payload, by dotted path — e.g. "
        "{{payload.changes.field}}. Lists join with commas.",
    ),
)


def all_tokens() -> tuple[TokenInfo, ...]:
    """The engine's own tokens plus every registered provider's (RADD-1324) —
    what the catalog serves and what the reserved roots derive from."""
    from radd.kernel.registry import registries

    contributed = tuple(
        TokenInfo(f"{{{{{provider.root}.{field_name}}}}}", description)
        for provider in registries.token_providers.values()
        for field_name, description in provider.tokens
    )
    return (*TOKENS, *contributed)


def reserved_roots() -> frozenset[str]:
    """The first segment of every documented token — words a node may NOT be
    named (spec 120). Derived, never listed, and memoised per set of providers
    because `Renderer` asks per token."""
    from radd.kernel.registry import registries

    return _roots(tuple(sorted(registries.token_providers)))


@lru_cache(maxsize=8)
def _roots(provider_roots: tuple[str, ...]) -> frozenset[str]:
    core = {token.token.strip("{} ").split(".", 1)[0] for token in TOKENS}
    return frozenset(core | set(provider_roots))


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
    if token.startswith("item.") and item_ctx is not None:
        value = item_ctx.get(token.removeprefix("item."))
        return None if value is None else str(value)
    # RADD-1324: a root an entity's owner registered — `page`, `comment`, a
    # plugin's `milestone` — answered from the refs the event carries.
    from radd.kernel.registry import registries

    root, dot, field_name = token.partition(".")
    provider = registries.token_providers.get(root) if dot else None
    if provider is not None:
        return provider.resolve(field_name, facts.payload)
    return None


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
    """One action invocation's template resolver (spec 120). An object because
    it reports on itself: the text, what each token became (`resolved`, for the
    dry run), and which VARIABLE tokens missed (`misses`, so the action skips
    instead of writing a literal `{{triage.priority}}`). Every other unresolved
    token still degrades verbatim — `{{payload.foo}}` missing on an event is a
    normal miss, not a reason to disable a working automation.
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

        return TOKEN_RE.sub(replace, str(value))

    def line(self, value: Any) -> str:
        """Render, then collapse whitespace — for params that NAME something or
        become a header, never a body. A newline in a mail header makes the
        transport refuse it (dry run says "Would apply", nothing is sent), and
        "In\nProgress" must still match the state "In Progress"."""
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


class MissingTemplateOutput(ValueError):
    """A required named producer did not provide the value this action needs."""
