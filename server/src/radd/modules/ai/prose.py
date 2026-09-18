"""What of a markdown body is PROSE — the part a language model should read.

RADD-1232: a description with three screenshots is three `![image](…)` lines
whose targets are attachment URLs (or, pasted from a clipboard, base64 data
URIs of tens of kilobytes). Every prompt this module builds — the summary, the
similar-issues rerank, the automation context, the embedding text — was
handing those to the model verbatim: a token budget spent on opaque strings,
slower answers, and a model that "sees" an image URL and invents what is in
it. None of it is prose. This is the one place that decides what is.

Kept: words, code (a stack trace IS the report), link TEXT (the words someone
chose, not the address). Dropped: image references, data URIs, HTML tags,
bare URLs longer than a few words, and the `radd:*` extension fences whose
body is configuration, not text. Pure and cheap — it runs on every embed.
"""

from __future__ import annotations

import re

#: `![alt](target)` — the alt is kept, since it is the one thing the author
#: wrote about the picture.
_IMAGE = re.compile(r"!\[(?P<alt>[^\]]*)\]\([^)]*\)")
#: `[text](target)` → text. A link's words are prose; its address is not.
_LINK = re.compile(r"\[(?P<text>[^\]]+)\]\([^)]*\)")
#: `<img …>`, `<a href=…>`, any tag — markdown bodies carry pasted HTML.
_TAG = re.compile(r"<[^>\n]{1,400}>")
#: A data URI anywhere: the biggest single waste, and never words.
_DATA_URI = re.compile(r"data:[a-z0-9.+/-]+;base64,[A-Za-z0-9+/=\s]{16,}", re.IGNORECASE)
#: A bare URL. Replaced by a marker so "see <link>" still reads as a sentence.
_BARE_URL = re.compile(r"(?<![\w(\[])(?:https?://|www\.)[^\s<>()\]]{4,}")
#: A `radd:<name>` fence and its body — extension CONFIGURATION (RADD-709).
_EXTENSION_FENCE = re.compile(r"```radd:[^\n]*\n.*?```", re.DOTALL)
_MANY_BLANK_LINES = re.compile(r"\n{3,}")

#: What a dropped picture leaves behind, so the model knows one was there.
IMAGE_MARKER = "[image]"
#: What a dropped bare address leaves behind.
LINK_MARKER = "[link]"


def prose(markdown: str) -> str:
    """`markdown` with everything that is not words for a model taken out."""
    if not markdown:
        return ""
    text = _EXTENSION_FENCE.sub("", markdown)
    text = _DATA_URI.sub("", text)
    text = _IMAGE.sub(lambda m: f"{IMAGE_MARKER} {m.group('alt')}".strip(), text)
    text = _LINK.sub(lambda m: m.group("text"), text)
    text = _TAG.sub("", text)
    text = _BARE_URL.sub(LINK_MARKER, text)
    text = _MANY_BLANK_LINES.sub("\n\n", text)
    return text.strip()
