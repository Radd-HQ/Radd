"""Confluence macros → Radd page extensions. Anything unmapped defaults to
UNSUPPORTED (a card keeping name + params), never STRIP: a page whose content was
the macro must not import empty, and a later renderer upgrades it on re-convert."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..types import MacroAction

#: Extension names (strings: `pages` owns the enum). Plan validation checks the
#: plan's rows against the registry; this built-in table is not checked.
EXT_TOC = "toc"
EXT_CHILDREN = "children"
EXT_CALLOUT = "callout"
EXT_INCLUDE = "include"
EXT_LABEL_LIST = "label-list"
EXT_EXPAND = "expand"
EXT_ITEMS = "items"
EXT_UNSUPPORTED = "unsupported-macro"
EXT_MEDIA = "media"


@dataclass(frozen=True, slots=True)
class MacroSpec:
    """What one Confluence macro name becomes."""

    action: MacroAction
    extension: str = ""
    #: Confluence parameter name → extension parameter name, plus a converter.
    params: Callable[[dict[str, str], str], dict] | None = None
    note: str = ""


def _depth_params(*keys: str) -> Callable[[dict[str, str], str], dict]:
    """A `depth` (clamped 1–6) from the first of `keys` the macro sets."""

    def build(p: dict[str, str], body: str) -> dict:
        depth = next((p[key] for key in keys if p.get(key)), "")
        return {"depth": max(1, min(6, int(depth)))} if depth.isdigit() else {}

    return build


_toc_params = _depth_params("maxLevel", "maxlevel")
_children_params = _depth_params("depth", "maxLevel")


#: Confluence's four note macros are one Radd callout with a `kind`. `panel` joins
#: them as `info`: it is a titled box, which is what a callout is.
_CALLOUT_KIND = {
    "info": "info",
    "note": "info",
    "tip": "success",
    "warning": "warning",
    "panel": "info",
}


def _callout_params(kind: str) -> Callable[[dict[str, str], str], dict]:
    def build(p: dict[str, str], body: str) -> dict:
        out: dict = {"kind": kind}
        if p.get("title"):
            out["title"] = p["title"]
        if body.strip():
            out["text"] = body.strip()
        return out

    return build


def _include_params(p: dict[str, str], body: str) -> dict:
    # The page reference lives in the macro's rich-text body as <ri:page>, which
    # the converter resolves before calling this; it arrives here as `body`.
    return {"page": body.strip()} if body.strip() else {}


def _label_list_params(p: dict[str, str], body: str) -> dict:
    raw = p.get("labels") or p.get("label") or ""
    if not raw and p.get("cql"):
        # `label = "runbook"` / `label in ("a","b")` — take the first quoted value
        # rather than attempting a CQL parser for a parameter with one shape.
        import re

        found = re.findall(r'"([^"]+)"', p["cql"])
        raw = found[0] if found else ""
    first = raw.replace(",", " ").split()
    return {"label": first[0]} if first else {}


def _template_params(p: dict[str, str], body: str) -> dict:
    """Confluence's create-from-template button → `radd:new-from-template`, which
    already exists and does the same job."""
    out: dict = {}
    template = p.get("templateName") or p.get("template") or ""
    if template:
        out["template"] = template
    if p.get("buttonLabel") or p.get("title"):
        out["label"] = p.get("buttonLabel") or p.get("title", "")
    return out


def _expand_params(p: dict[str, str], body: str) -> dict:
    return {"title": p.get("title", "") or "Details", "text": body.strip()}


#: The built-in table. A plan's macro mapping starts from this and the admin
#: overrides it; anything absent here defaults to UNSUPPORTED.
BUILTIN_MACROS: dict[str, MacroSpec] = {
    "toc": MacroSpec(MacroAction.EXTENSION, EXT_TOC, _toc_params),
    "children": MacroSpec(MacroAction.EXTENSION, EXT_CHILDREN, _children_params),
    "pagetree": MacroSpec(
        MacroAction.EXTENSION, EXT_CHILDREN, _children_params,
        note="a pagetree rooted elsewhere becomes this page's children",
    ),
    "include": MacroSpec(MacroAction.EXTENSION, EXT_INCLUDE, _include_params),
    "excerpt-include": MacroSpec(MacroAction.EXTENSION, EXT_INCLUDE, _include_params),
    "contentbylabel": MacroSpec(MacroAction.EXTENSION, EXT_LABEL_LIST, _label_list_params),
    "expand": MacroSpec(MacroAction.EXTENSION, EXT_EXPAND, _expand_params),
    # Native markdown — no extension involved.
    # INLINE macros never become a `radd:*` fence (block-level: one inside a table
    # cell ends the table). `status` loses its colour, deliberately.
    "status": MacroSpec(MacroAction.NATIVE, note="inline code — the colour is lost"),
    # `details` and `excerpt` are containers: what matters is their body.
    "details": MacroSpec(MacroAction.NATIVE, note="its body, inlined"),
    # A real player, not a card: the recording IS the page's content.
    "multimedia": MacroSpec(
        MacroAction.NATIVE, EXT_MEDIA, note="a playable video or audio attachment"
    ),
    "viewfile": MacroSpec(
        MacroAction.NATIVE, EXT_MEDIA, note="a playable attachment, or a link"
    ),
    "widget": MacroSpec(
        MacroAction.NATIVE, EXT_MEDIA, note="an embedded external video"
    ),
    # The Confluence mermaid apps carry the diagram source as their body; the wiki
    # renders ```mermaid natively.
    "mermaid": MacroSpec(MacroAction.NATIVE, note="a rendered mermaid diagram"),
    "mermaid-cloud": MacroSpec(MacroAction.NATIVE, note="a rendered mermaid diagram"),
    "mermaid-diagram": MacroSpec(MacroAction.NATIVE, note="a rendered mermaid diagram"),
    "code": MacroSpec(MacroAction.NATIVE, note="a fenced code block"),
    "noformat": MacroSpec(MacroAction.NATIVE, note="a fenced code block"),
    "anchor": MacroSpec(MacroAction.STRIP, note="markdown headings carry their own anchors"),
    # Found by running the census over a real space (RADD-1022). Each was landing
    # as an "unsupported" card while having an obvious home.
    "nocomments": MacroSpec(
        MacroAction.STRIP, note="a Confluence display setting, not content"
    ),
    "toc-zone": MacroSpec(
        MacroAction.EXTENSION, EXT_TOC, _toc_params, note="a toc with its body inlined"
    ),
    "create-from-template": MacroSpec(
        MacroAction.EXTENSION, "new-from-template", _template_params
    ),
    "recently-updated": MacroSpec(
        MacroAction.STRIP, note="a live feed with no equivalent — the tree replaces it"
    ),
    "excerpt": MacroSpec(MacroAction.NATIVE, note="its body, inlined"),
    "section": MacroSpec(MacroAction.NATIVE, note="layout — its body, inlined"),
    "column": MacroSpec(MacroAction.NATIVE, note="layout — its body, inlined"),
    "jira": MacroSpec(MacroAction.NATIVE, note="an issue reference, or a link"),
    # NATIVE rather than EXTENSION even though it produces a `radd:items` fence:
    # the block it emits depends on whether the JQL translated, and only the
    # converter knows that. A declarative params function cannot report a problem.
    "jiraissues": MacroSpec(
        MacroAction.NATIVE, EXT_ITEMS, note="an SLQ query table, or the original JQL"
    ),
}

for _name, _kind in _CALLOUT_KIND.items():
    BUILTIN_MACROS[_name] = MacroSpec(
        MacroAction.EXTENSION, EXT_CALLOUT, _callout_params(_kind)
    )


def spec_for(name: str, overrides: dict[str, MacroSpec] | None = None) -> MacroSpec:
    """The plan's decision for a macro, else the built-in, else UNSUPPORTED."""
    if overrides and name in overrides:
        return overrides[name]
    return BUILTIN_MACROS.get(name, MacroSpec(MacroAction.UNSUPPORTED))


def overrides_from(rows) -> dict[str, MacroSpec]:
    """The plan's macro rows as converter overrides; a row that agrees with the
    built-in contributes nothing, so the built-in keeps its param builder."""
    out: dict[str, MacroSpec] = {}
    for row in rows or ():
        name = getattr(row, "name", "")
        action = getattr(row, "action", None)
        if not name or action is None or action is MacroAction.IGNORE:
            continue
        builtin = BUILTIN_MACROS.get(name)
        extension = getattr(row, "extension", "") or ""
        if builtin and builtin.action is action and builtin.extension == extension:
            continue
        out[name] = MacroSpec(
            action=action,
            extension=extension,
            # Keep the builder when the target is unchanged; a redirected macro
            # has no parameter mapping to inherit.
            params=builtin.params if builtin and builtin.extension == extension else None,
        )
    return out
