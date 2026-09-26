"""What of a markdown body is PROSE — the part a language model should read
(RADD-1232): the one place every prompt and the embedding text decide it.

Kept: words, code (a stack trace IS the report), link TEXT. Dropped: image
references, data URIs (tens of kilobytes of budget a model would "see" and
invent from), HTML tags, long bare URLs, and `radd:*` fences (configuration,
not text). Pure and cheap — it runs on every embed.
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
