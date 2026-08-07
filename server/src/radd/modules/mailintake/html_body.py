"""HTML → markdown-ish text for HTML-only mail (RADD-956).

Inbound mail is the most reliably hostile input Radd accepts: anyone with an
address can send it and nothing in it is trustworthy. An HTML-only message is
also completely ordinary — Outlook, most marketing systems and plenty of phones
send nothing else — so dropping it produces a blank ticket, which is what
happened before this.

**This strips markup rather than sanitising it, and that is the stronger
choice.** Sanitising keeps an allow-list of tags and attributes, so its safety is
the completeness of that list; every sanitiser CVE is a gap in one. Here nothing
survives as markup at all: the output is text, the body is rendered as markdown
downstream, and Radd's own viewer escapes raw HTML anyway (verified against the
real renderer in RADD-942). There is no allow-list to get wrong.

It is deliberately not a general HTML-to-markdown converter. Tables, nested
lists and layout are flattened. The goal is a readable ticket body, not a
faithful reproduction of a marketing email.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

#: Content inside these never reaches the output, tags and text alike.
DROPPED_CONTENT = {"script", "style", "head", "title", "noscript", "template", "svg"}

#: Tags that end the current line.
BREAKING = {"br", "p", "div", "tr", "table", "ul", "ol", "blockquote", "section", "article"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._dropping = 0
        self._href: str | None = None
        self._link_text: list[str] = []

    # --- structure ---

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROPPED_CONTENT:
            self._dropping += 1
            return
        if self._dropping:
            return
        if tag in BREAKING or tag in HEADINGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("\n- ")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            # Only http(s) and mailto survive as links. `javascript:` and `data:`
            # are the two that matter, and an allow-list is right here because
            # the set of schemes worth keeping is genuinely tiny.
            self._href = href if re.match(r"^(?:https?:|mailto:)", href, re.I) else None
            self._link_text = []
        if tag == "img":
            alt = dict(attrs).get("alt") or ""
            # The src is deliberately dropped: a remote image in a ticket body is
            # a tracking pixel far more often than it is content, and real
            # attachments arrive as parts.
            if alt:
                self.parts.append(f"[image: {alt}]")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROPPED_CONTENT:
            self._dropping = max(0, self._dropping - 1)
            return
        if self._dropping:
            return
        if tag == "a":
            text = "".join(self._link_text).strip()
            if self._href and text and text != self._href:
                self.parts.append(f"[{text}]({self._href})")
            elif self._href:
                self.parts.append(self._href)
            else:
                self.parts.append(text)
            self._href = None
            self._link_text = []
        if tag in BREAKING or tag in HEADINGS:
            self.parts.append("\n")

    # --- text ---

    def handle_data(self, data: str) -> None:
        if self._dropping:
            return
        if self._href is not None:
            self._link_text.append(data)
            return
        self.parts.append(data)


def html_to_text(html: str) -> str:
    """Readable text from an HTML mail part. Never raises: a malformed document
    is the normal case, and a parse failure must not turn into a bounce."""
    if not html:
        return ""
    extractor = _Extractor()
    try:
        extractor.feed(html)
        extractor.close()
    except Exception:  # noqa: BLE001 — malformed HTML is input, not an error
        pass
    text = "".join(extractor.parts)
    text = text.replace(" ", " ")            # nbsp, which mail is full of
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)        # collapse the div soup
    return text.strip()
