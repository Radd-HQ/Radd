"""Confluence storage format → Radd markdown (spec 117).

Pure: no DB, no network, no session. Everything that needs the world — resolving
an attachment to its imported URL, a page id to a Radd page, a Jira key to an
imported item — arrives as a callable on `ConvertContext`, each with a degradation
that is honest rather than empty. That is what lets the converter run repeatedly
over a cached body as the plan's mappings change, which is the whole workflow.

Block vs inline is the shape that matters. `radd:*` fences are BLOCK-level, so a
macro that Confluence renders inline (a `status` lozenge, a single-key `jira`
reference, a user mention) cannot become one. Two of those three have native
markdown equivalents Radd already renders; the lozenge degrades to inline code,
which is lossy and deliberately so — there is no inline extension seam in the
kernel and inventing one for a coloured lozenge is not proportionate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from ..types import MacroAction, MappingSection, Problem, ProblemKind
from . import macros as macro_table
from .macros import MacroSpec
from .tree import Node, parse

#: Markdown that would be read as syntax if it appeared in prose.
_ESCAPE_RE = re.compile(r"([\\`*_\[\]<>|])")

_HEADINGS = {f"h{n}": n for n in range(1, 7)}
_INLINE_STRONG = {"strong", "b"}
_INLINE_EM = {"em", "i"}
_INLINE_DEL = {"del", "s", "strike"}

#: Constructs whose meaning lives in their ATTRIBUTES, so walking their children
#: yields nothing. `block()` must route these to the inline handler rather than
#: through the generic fallback, because storage format nests freely and a body
#: can be a bare `<ac:image>` with no wrapping paragraph.
_INLINE_TAGS = (
    {"a", "code", "time", "img", "ac:link", "ac:image"}
    | _INLINE_STRONG | _INLINE_EM | _INLINE_DEL
)

#: `/download/attachments/<pageId>/<filename>?version=…` — the src a plain `<img>`
#: carries. Confluence writes BOTH forms: `<ac:image><ri:attachment>` from the
#: editor's insert, and a bare `<img>` with an absolute URL from a paste or an
#: older editor. A converter that only knows the first silently drops every image
#: on the pages that use the second, which on a real corpus is most of them.
_DOWNLOAD_SRC_RE = re.compile(r"/download/attachments/\d+/([^?#]+)")

#: Extensions that get an <audio> player rather than a <video> one. Everything
#: else a `multimedia` macro embeds is video — including the .mp4 meeting
#: recordings that dominate a real wiki.
_AUDIO_EXTENSIONS = frozenset({"mp3", "wav", "ogg", "oga", "m4a", "aac", "flac"})


def _find_attachment(node: "Node | None") -> str:
    """The first `ri:filename` anywhere beneath a node."""
    if node is None:
        return ""
    if node.tag == "ri:attachment":
        return node.attrs.get("ri:filename", "")
    for child in node.children:
        if isinstance(child, Node):
            found = _find_attachment(child)
            if found:
                return found
    return ""


def _escape(text: str) -> str:
    return _ESCAPE_RE.sub(r"\\\1", text)


def _md_url(url: str) -> str:
    """A markdown link target that survives a space.

    Confluence filenames routinely contain them ("Screenshot 2025-02-07 at
    15.37.38.png"), and `![alt](a b.png)` is not a link at all — the renderer
    shows the literal text. Angle brackets are the markdown-native escape, and
    they are harmless on a URL that never needed them.
    """
    return f"<{url}>" if url and (" " in url or ")" in url) else url


@dataclass(slots=True)
class ConvertResult:
    markdown: str
    problems: list[Problem] = field(default_factory=list)
    #: Foreign page ids this body links to — the run turns unresolved ones into
    #: pending refs rather than dropping the link.
    page_refs: set[str] = field(default_factory=set)
    attachment_refs: set[str] = field(default_factory=set)
    jira_keys: set[str] = field(default_factory=set)
    macros_seen: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class ConvertContext:
    """The world, as callables. Every default degrades visibly, never silently."""

    #: filename → the URL of the imported attachment, or "" if not imported.
    attachment_url: Callable[[str], str] = lambda name: ""
    #: foreign page id → a Radd path, or "" when it is not imported (yet).
    page_url: Callable[[str], str] = lambda page_id: ""
    #: page TITLE → a Radd path. Confluence links by title far more than by id.
    page_url_by_title: Callable[[str, str], str] = lambda title, space: ""
    #: username → (display name, Radd user id) — "" id means unresolved.
    user_ref: Callable[[str], tuple[str, str]] = lambda username: (username, "")
    #: Jira key → True when spec 100 imported it into Radd under the same key.
    item_exists: Callable[[str], bool] = lambda key: False
    #: Base URL for the external fallback when a reference cannot be resolved.
    jira_base_url: str = ""
    confluence_base_url: str = ""
    macro_overrides: dict[str, MacroSpec] = field(default_factory=dict)


def convert(storage: str, context: ConvertContext | None = None) -> ConvertResult:
    """Convert one storage-format body. Never raises on malformed input."""
    ctx = context or ConvertContext()
    result = ConvertResult(markdown="")
    renderer = _Renderer(ctx, result)
    body = renderer.blocks(parse(storage))
    result.markdown = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n" if body.strip() else ""
    return result


class _Renderer:
    def __init__(self, ctx: ConvertContext, result: ConvertResult):
        self.ctx = ctx
        self.result = result

    # --- block level ---

    def blocks(self, node: Node) -> str:
        out: list[str] = []
        for child in node.children:
            if isinstance(child, str):
                if child.strip():
                    out.append(_escape(child.strip()))
                continue
            rendered = self.block(child)
            if rendered:
                out.append(rendered)
        return "\n\n".join(part for part in out if part)

    def block(self, node: Node) -> str:
        tag = node.tag
        if tag in _HEADINGS:
            text = self.inline(node).strip()
            return f"{'#' * _HEADINGS[tag]} {text}" if text else ""
        if tag == "p":
            return self.inline(node).strip()
        if tag in ("ul", "ol"):
            return self.list_(node, ordered=tag == "ol")
        if tag == "table":
            return self.table(node)
        if tag == "blockquote":
            inner = self.blocks(node)
            return "\n".join(f"> {line}" for line in inner.splitlines()) if inner else ""
        if tag == "pre":
            return f"```\n{node.text().strip()}\n```"
        if tag == "hr":
            return "---"
        if tag == "ac:structured-macro":
            return self.macro(node)
        if tag == "ac:task-list":
            return self.tasks(node)
        if tag == "ac:layout-cell" or tag == "ac:layout-section" or tag == "ac:layout":
            # Confluence page layouts are chrome around content; markdown has no
            # columns, so the content flows in document order.
            return self.blocks(node)
        if tag in ("div", "span", "ac:rich-text-body", "#root", "tbody", "thead"):
            return self.blocks(node)
        if tag == "ac:placeholder":
            return ""  # editor chrome, never content
        # An INLINE construct standing alone as a block. Storage format nests
        # freely, so a body can be a bare <ac:image> or <ac:link> with no wrapping
        # <p> — and routing those through the block fallback rendered nothing at
        # all, because their content lives in attributes rather than in children.
        if tag in _INLINE_TAGS:
            return self.inline_node(node).strip()
        # Anything unrecognised: keep its content rather than dropping the page.
        inner = self.blocks(node)
        return inner or self.inline(node).strip()

    def list_(self, node: Node, *, ordered: bool, depth: int = 0) -> str:
        lines: list[str] = []
        index = 1
        for item in node.find_all("li"):
            marker = f"{index}." if ordered else "-"
            index += 1
            # A list item's own text, then any nested lists beneath it.
            own = Node("li", {}, [c for c in item.children
                                  if not (isinstance(c, Node) and c.tag in ("ul", "ol"))])
            text = self.inline(own).strip() or self.blocks(own).strip()
            pad = "  " * depth
            first, *rest = (text or "").splitlines() or [""]
            lines.append(f"{pad}{marker} {first}")
            lines.extend(f"{pad}  {line}" for line in rest)
            for nested in item.children:
                if isinstance(nested, Node) and nested.tag in ("ul", "ol"):
                    lines.append(
                        self.list_(nested, ordered=nested.tag == "ol", depth=depth + 1)
                    )
        return "\n".join(line for line in lines if line.strip())

    def tasks(self, node: Node) -> str:
        """`ac:task-list` is a markdown checklist — native, not an extension."""
        lines: list[str] = []
        for task in node.find_all("ac:task"):
            status = task.find("ac:task-status")
            body = task.find("ac:task-body")
            done = (status.text().strip() if status else "") == "complete"
            text = self.inline(body).strip() if body else ""
            lines.append(f"- [{'x' if done else ' '}] {text}")
        return "\n".join(lines)

    def table(self, node: Node) -> str:
        """A markdown table. `colgroup` widths are dropped — markdown cannot
        express them, and a table that renders is worth more than one that does
        not."""
        rows: list[list[str]] = []
        for section in (node, node.find("tbody"), node.find("thead")):
            if section is None:
                continue
            for tr in section.find_all("tr"):
                cells = [
                    self.inline(cell).strip().replace("\n", " ")
                    for cell in tr.children
                    if isinstance(cell, Node) and cell.tag in ("td", "th")
                ]
                if cells:
                    rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        # Markdown requires a header row. A table whose first row is data gets an
        # empty one rather than losing its first line to a header it never had.
        first_is_header = any(
            isinstance(c, Node) and c.tag == "th"
            for section in (node, node.find("thead"), node.find("tbody"))
            if section is not None
            for tr in section.find_all("tr")[:1]
            for c in tr.children
        )
        header = rows[0] if first_is_header else [""] * width
        body = rows[1:] if first_is_header else rows
        lines = [
            "| " + " | ".join(c or " " for c in header) + " |",
            "| " + " | ".join("---" for _ in range(width)) + " |",
        ]
        lines += ["| " + " | ".join(c or " " for c in row) + " |" for row in body]
        return "\n".join(lines)

    # --- inline level ---

    def inline(self, node: Node | None) -> str:
        if node is None:
            return ""
        out: list[str] = []
        for child in node.children:
            if isinstance(child, str):
                out.append(_escape(child))
                continue
            out.append(self.inline_node(child))
        return "".join(out)

    def inline_node(self, node: Node) -> str:
        tag = node.tag
        if tag in _INLINE_STRONG:
            inner = self.inline(node).strip()
            return f"**{inner}**" if inner else ""
        if tag in _INLINE_EM:
            inner = self.inline(node).strip()
            return f"*{inner}*" if inner else ""
        if tag in _INLINE_DEL:
            inner = self.inline(node).strip()
            return f"~~{inner}~~" if inner else ""
        if tag == "code":
            return f"`{node.text().strip()}`"
        if tag == "br":
            return "\n"
        if tag == "a":
            return self.anchor(node)
        if tag == "time":
            return _escape(node.attrs.get("datetime", "") or node.text())
        if tag == "ac:placeholder":
            return ""
        if tag == "ac:image":
            return self.image(node)
        if tag == "img":
            return self.html_image(node)
        if tag == "ac:link":
            return self.ac_link(node)
        if tag == "ac:structured-macro":
            return self.macro(node, inline=True)
        if tag == "ac:task-list":
            return "\n" + self.tasks(node)
        if tag in _HEADINGS or tag in ("p", "div", "li", "td", "th", "span",
                                       "ac:rich-text-body", "ac:plain-text-body"):
            return self.inline(node)
        if tag in ("ul", "ol"):
            return "\n" + self.list_(node, ordered=tag == "ol")
        if tag == "table":
            return "\n" + self.table(node)
        return self.inline(node)

    def anchor(self, node: Node) -> str:
        href = node.attrs.get("href", "")
        text = self.inline(node).strip() or href
        if not href:
            return text
        # A link into the Confluence instance we are importing FROM is a link into
        # the wiki we are importing TO, when its target came across.
        match = re.search(r"pageId=(\d+)", href)
        if match:
            self.result.page_refs.add(match.group(1))
            resolved = self.ctx.page_url(match.group(1))
            if resolved:
                return f"[{text}]({resolved})"
        return f"[{text}]({href})"

    def image(self, node: Node) -> str:
        attachment = node.find("ri:attachment")
        url_node = node.find("ri:url")
        alt = node.attrs.get("ac:alt", "")
        if url_node is not None:
            return f"![{alt}]({_md_url(url_node.attrs.get('ri:value', ''))})"
        if attachment is None:
            return ""
        filename = attachment.attrs.get("ri:filename", "")
        self.result.attachment_refs.add(filename)
        url = self.ctx.attachment_url(filename)
        if not url:
            self._problem(
                ProblemKind.ATTACHMENT,
                f"image {filename!r} has no imported attachment",
                subject=filename,
            )
            return f"![{alt or filename}]({_md_url(filename)})"
        # RADD-751: the width rides in the URL as ?w=, so the endpoint serves fewer
        # bytes than the original when the document asks for a smaller image.
        width = node.attrs.get("ac:width", "")
        if width.isdigit():
            url = f"{url}{'&' if '?' in url else '?'}w={width}"
        return f"![{alt or filename}]({_md_url(url)})"

    def html_image(self, node: Node) -> str:
        """A plain `<img>`, which on a real corpus is the COMMON form.

        Its `src` is an absolute `/download/attachments/<pageId>/<file>` URL. The
        filename is what identifies the attachment, so it routes through exactly
        the same resolver as `<ac:image>`; an image from somewhere else keeps its
        URL, since an external image is still an image.
        """
        src = node.attrs.get("src", "")
        alt = node.attrs.get("alt", "")
        match = _DOWNLOAD_SRC_RE.search(src)
        if match is None:
            return f"![{alt}]({_md_url(src)})" if src else ""
        from urllib.parse import unquote

        filename = unquote(match.group(1))
        self.result.attachment_refs.add(filename)
        url = self.ctx.attachment_url(filename)
        if not url:
            self._problem(
                ProblemKind.ATTACHMENT,
                f"image {filename!r} has no imported attachment",
                subject=filename,
            )
            return f"![{alt or filename}]({_md_url(filename)})"
        width = node.attrs.get("width", "")
        if width.isdigit():
            url = f"{url}{'&' if '?' in url else '?'}w={width}"
        return f"![{alt or filename}]({_md_url(url)})"

    def ac_link(self, node: Node) -> str:
        """`<ac:link>` wraps a typed reference: a page, a user, an attachment."""
        body = node.find("ac:link-body") or node.find("ac:plain-text-link-body")
        label = self.inline(body).strip() if body is not None else ""

        user = node.find("ri:user")
        if user is not None:
            username = user.attrs.get("ri:username", "") or user.attrs.get("ri:userkey", "")
            name, user_id = self.ctx.user_ref(username)
            if user_id:
                # The mention token the markdown renderer already understands.
                return f"@[{name}]({user_id})"
            self._problem(
                ProblemKind.USER, f"mention of unknown user {username!r}",
                subject=username, section=MappingSection.USERS, mapping_key=username,
            )
            return f"@{name or username}"

        page = node.find("ri:page")
        if page is not None:
            title = page.attrs.get("ri:content-title", "")
            space = page.attrs.get("ri:space-key", "")
            url = self.ctx.page_url_by_title(title, space)
            text = label or title
            if url:
                return f"[{text}]({url})"
            self.result.page_refs.add(title)
            self._problem(
                ProblemKind.LINK, f"link to a page outside this import: {title!r}",
                subject=title,
            )
            return f"[{text}]({self._external_page(title, space)})"

        attachment = node.find("ri:attachment")
        if attachment is not None:
            filename = attachment.attrs.get("ri:filename", "")
            self.result.attachment_refs.add(filename)
            url = self.ctx.attachment_url(filename)
            return f"[{label or filename}]({_md_url(url or filename)})"
        return label

    def _external_page(self, title: str, space: str) -> str:
        base = self.ctx.confluence_base_url.rstrip("/")
        if not base:
            return "#"
        space_part = f"spaceKey={space}&" if space else ""
        return f"{base}/display/{space}/{title.replace(' ', '+')}" if space else \
            f"{base}/pages/viewpage.action?{space_part}title={title.replace(' ', '+')}"

    # --- macros ---

    def macro(self, node: Node, *, inline: bool = False) -> str:
        name = node.attrs.get("ac:name", "")
        self.result.macros_seen[name] = self.result.macros_seen.get(name, 0) + 1
        params = {
            p.attrs.get("ac:name", ""): p.text().strip()
            for p in node.find_all("ac:parameter")
        }
        plain = node.find("ac:plain-text-body")
        rich = node.find("ac:rich-text-body")
        raw_body = plain.text() if plain is not None else ""
        spec = macro_table.spec_for(name, self.ctx.macro_overrides)

        if spec.action is MacroAction.STRIP:
            return ""
        if spec.action is MacroAction.NATIVE:
            return self.native_macro(name, params, raw_body, rich, node, inline=inline)
        if spec.action is MacroAction.EXTENSION:
            body_text = raw_body
            if rich is not None:
                # `include` names its target as <ri:page> inside the rich body; the
                # rest want their body as markdown.
                page = rich.find("ac:link") or rich
                ri_page = page.find("ri:page") if page is not None else None
                body_text = (
                    ri_page.attrs.get("ri:content-title", "")
                    if ri_page is not None
                    else self.blocks(rich)
                )
            built = spec.params(params, body_text) if spec.params else {}
            return self.fence(spec.extension, built)
        return self.unsupported(name, params, raw_body, rich)

    def native_macro(
        self, name: str, params: dict[str, str], raw_body: str, rich: Node | None,
        node: Node | None = None, *, inline: bool,
    ) -> str:
        if name in ("code", "noformat"):
            language = params.get("language", "") if name == "code" else ""
            return f"```{language}\n{raw_body.strip()}\n```"
        if name == "status":
            # Inline by nature: a fence here would terminate the table cell it
            # almost always sits in. The colour is dropped — see macros.py.
            title = params.get("title", "").strip()
            return f"`{title}`" if title else ""
        if name in ("excerpt", "section", "column", "details"):
            # Containers. Inlined when we are inline, so a container inside a
            # paragraph does not inject block structure into it.
            if rich is None:
                return raw_body.strip()
            return self.inline(rich).strip() if inline else self.blocks(rich)
        if name == "jira":
            return self.jira_macro(params, inline=inline)
        if name == "jiraissues":
            return self.items_fence(params.get("jqlQuery", "") or params.get("jql", ""))
        if name in ("multimedia", "viewfile", "widget"):
            return self.media_fence(name, params, rich, node)
        return raw_body.strip()

    def media_fence(
        self, name: str, params: dict[str, str], rich: Node | None,
        node: Node | None = None,
    ) -> str:
        """A playable attachment.

        `multimedia` IS the content of the pages that use it — a meeting recording
        carded as "unsupported" is the page missing its point. The filename is
        resolved through the same attachment resolver images use, so the player
        points at the imported file rather than at Confluence.
        """
        filename = params.get("name", "") or params.get("file", "")
        # The real markup puts the file in an ELEMENT inside the parameter:
        #   <ac:parameter ac:name="name"><ri:attachment ri:filename="x.mp4"/></ac:parameter>
        # so reading parameters as text found an empty string and carded the macro
        # while the video sat right there. Search the whole macro for the
        # reference rather than guessing which shape this instance writes.
        if not filename:
            for scope in (node, rich):
                found = _find_attachment(scope)
                if found:
                    filename = found
                    break
        # `widget` embeds an external URL (YouTube and friends) rather than a file.
        external = params.get("url", "")
        if not filename and external:
            return self.fence(macro_table.EXT_MEDIA, {"src": external, "kind": "video"})
        if not filename:
            return self.unsupported(name, params, "", rich)

        self.result.attachment_refs.add(filename)
        url = self.ctx.attachment_url(filename)
        if not url:
            self._problem(
                ProblemKind.ATTACHMENT,
                f"{filename!r} has no imported attachment to play",
                subject=filename,
            )
        kind = "audio" if filename.lower().rsplit(".", 1)[-1] in _AUDIO_EXTENSIONS else "video"
        return self.fence(
            macro_table.EXT_MEDIA,
            {"src": url or filename, "kind": kind, "title": filename},
        )

    def jira_macro(self, params: dict[str, str], *, inline: bool) -> str:
        """The join between the two halves of the migration.

        A single-key reference becomes a real Radd issue mention when spec 100
        already imported that key — which makes it render as a live chip and feeds
        `item_page_links` for free, because `pages/mentions.py` reconciles derived
        links from body text. A key that was not imported keeps an honest external
        link rather than becoming a stub item nobody filed.

        A JQL-shaped `jira` macro is a QUERY, not a reference, so it goes the same
        way `jiraissues` does — through `radd:items`.
        """
        key = params.get("key", "").strip()
        if not key:
            jql = params.get("jqlQuery", "") or params.get("jql", "")
            return self.items_fence(jql)
        self.result.jira_keys.add(key)
        if self.ctx.item_exists(key):
            return f"#[{key}]({key})"
        base = self.ctx.jira_base_url.rstrip("/")
        return f"[{key}]({base}/browse/{key})" if base else key

    def items_fence(self, jql: str) -> str:
        """A JQL table becomes an SLQ table.

        Translation is best effort, and a failure is NOT an import failure: the
        block keeps the original JQL and marks itself unsupported, so the page
        shows what the query was and a person fixes it. A silently mistranslated
        query that returns plausible rows is far worse than one that admits it
        needs a human.
        """
        slq, ok = translate_jql(jql)
        if ok:
            return self.fence(macro_table.EXT_ITEMS, {"query": slq, "source_jql": jql})
        self._problem(
            ProblemKind.MACRO,
            "a Jira query could not be translated to SLQ — imported for review",
            subject=jql[:120], section=MappingSection.MACROS, mapping_key="jiraissues",
        )
        return self.fence(
            macro_table.EXT_ITEMS, {"query": "", "source_jql": jql, "unsupported": True}
        )

    def unsupported(
        self, name: str, params: dict[str, str], raw_body: str, rich: Node | None
    ) -> str:
        """The honest fallback: name and parameters preserved, visible on the page.

        Never STRIP — a page whose content was the macro would import empty, and
        nobody would know to look for it.
        """
        self._problem(
            ProblemKind.MACRO,
            f"macro {name!r} has no mapping — imported as an unsupported block",
            subject=name, section=MappingSection.MACROS, mapping_key=name,
        )
        payload: dict = {"macro": name}
        if params:
            payload["params"] = params
        body = raw_body.strip() or (self.blocks(rich) if rich is not None else "")
        if body:
            payload["body"] = body
        return self.fence(macro_table.EXT_UNSUPPORTED, payload)

    def fence(self, extension: str, params: dict) -> str:
        """A `radd:<name>` block. The params are JSON, which is the wire format the
        SPA's `parseExtensionParams` reads."""
        body = json.dumps(params, indent=2, ensure_ascii=False) if params else "{}"
        return f"```radd:{extension}\n{body}\n```"

    def _problem(
        self, kind: ProblemKind, message: str, *, subject: str = "",
        section: MappingSection | None = None, mapping_key: str = "",
    ) -> None:
        self.result.problems.append(
            Problem(kind=kind, message=message, subject=subject,
                    section=section, mapping_key=mapping_key)
        )


# --- JQL → SLQ ----------------------------------------------------------------

#: The fields whose NAME is the same in both languages. SLQ names concepts, not
#: columns, and so does JQL for these — which is why the translation is a rename
#: table rather than a compiler.
_JQL_FIELDS = {
    "project": "project",
    "assignee": "assignee",
    "reporter": "reporter",
    "status": "status",
    "priority": "priority",
    "labels": "label",
    "type": "type",
    "issuetype": "type",
    "created": "created",
    "updated": "updated",
    "resolution": "resolution",
    "fixversion": "release",
}

_JQL_TOKEN = re.compile(
    r'(?P<field>[A-Za-z][\w]*)\s*(?P<op>!=|=|~|>=|<=|>|<|\bin\b|\bnot in\b)\s*'
    r'(?P<value>"[^"]*"|\'[^\']*\'|\([^)]*\)|[^\s()]+)',
    re.IGNORECASE,
)


def translate_jql(jql: str) -> tuple[str, bool]:
    """Best-effort JQL → SLQ. Returns (slq, fully_translated).

    Deliberately conservative: anything with a field this does not know, a
    function call, or an ORDER BY it cannot express reports `False` so the caller
    can preserve the original instead of shipping a query that looks right.
    """
    if not jql or not jql.strip():
        return "", False
    working = re.split(r"\border\s+by\b", jql, flags=re.IGNORECASE)[0].strip()
    # `currentUser()` is a VALUE, not grouping. Normalising it before the guard
    # below matters because its parentheses would otherwise read as boolean
    # grouping and refuse the most common query in any corpus.
    working = re.sub(r"\bcurrentUser\s*\(\s*\)", "currentUser", working, flags=re.IGNORECASE)
    if "(" in working and not re.search(r"\bin\b\s*\(", working, re.IGNORECASE):
        return "", False  # grouped boolean logic — not worth guessing at
    parts: list[str] = []
    consumed = 0
    for match in _JQL_TOKEN.finditer(working):
        field = match.group("field").lower()
        if field not in _JQL_FIELDS:
            return "", False
        value = match.group("value").strip()
        if "(" in value and ")" in value:
            value = value  # an IN list survives as-is; SLQ shares the syntax
        elif value.lower() in ("currentuser()", "currentuser"):
            value = "me"
        elif value.lower() == "empty":
            value = "EMPTY"
        op = match.group("op").upper() if match.group("op").lower() in ("in", "not in") \
            else match.group("op")
        parts.append(f"{_JQL_FIELDS[field]} {op} {value}")
        consumed += len(match.group(0))
    if not parts:
        return "", False
    # A translation that covered only part of the text is not a translation.
    stripped = re.sub(r"\s+(AND|OR)\s+", "", working, flags=re.IGNORECASE)
    if consumed < len(re.sub(r"\s+", "", stripped)) * 0.6:
        return "", False
    joiner = " AND " if re.search(r"\bAND\b", working, re.IGNORECASE) or len(parts) == 1 else " OR "
    return joiner.join(parts), True
