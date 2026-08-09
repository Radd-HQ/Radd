"""A tiny tree over Confluence storage format (spec 117).

**stdlib `html.parser`, deliberately.** Storage format is machine-generated
XHTML, so a real XML parser would work on the happy path — but a decade-old
corpus is full of pasted HTML, and a LENIENT parser degrades where a strict one
raises. `lxml` would buy speed this does not need in exchange for a C extension in
the image; `BeautifulSoup` is a wrapper we would only point at `html.parser`
anyway.

Namespaced tags need no special handling: `HTMLParser` reports
`<ac:structured-macro>` as the tag `ac:structured-macro`, which is exactly the key
the macro dispatch wants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

#: Elements that never have children. `ac:image` and `ri:*` are Confluence's own
#: and are frequently written self-closing; listing them means a malformed
#: document cannot swallow the rest of the page as their content.
VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
        "ri:page", "ri:user", "ri:attachment", "ri:space", "ri:url",
        "ri:blog-post", "ri:content-entity",
    }
)


@dataclass(slots=True)
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node | str"] = field(default_factory=list)

    def find(self, tag: str) -> "Node | None":
        for child in self.children:
            if isinstance(child, Node) and child.tag == tag:
                return child
        return None

    def find_all(self, tag: str) -> list["Node"]:
        return [c for c in self.children if isinstance(c, Node) and c.tag == tag]

    def text(self) -> str:
        """All descendant text, concatenated — for a node whose markup is noise."""
        out: list[str] = []
        for child in self.children:
            out.append(child if isinstance(child, str) else child.text())
        return "".join(out)


class _Builder(HTMLParser):
    def __init__(self) -> None:
        # convert_charrefs resolves &amp; and friends for us; storage format uses
        # them heavily and every consumer here wants the resolved text.
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self._stack: list[Node] = [self.root]

    # --- structure ---

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {k: (v or "") for k, v in attrs})
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack[-1].children.append(Node(tag, {k: (v or "") for k, v in attrs}))

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        # Walk back to the matching open tag rather than popping blindly: an
        # unclosed <p> inside a table cell is common in pasted content, and popping
        # one level would reparent the rest of the document into it.
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth].tag == tag:
                del self._stack[depth:]
                return

    # --- text ---

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)

    def unknown_decl(self, data: str) -> None:
        # `<![CDATA[ … ]]>` — how ac:plain-text-body carries a code sample. Losing
        # it would empty every `code` macro on the instance.
        if data.startswith("CDATA["):
            self._stack[-1].children.append(data[6:])


def parse(storage: str) -> Node:
    """Parse a storage-format body into a tree. Never raises on bad markup."""
    builder = _Builder()
    builder.feed(storage or "")
    builder.close()
    return builder.root
