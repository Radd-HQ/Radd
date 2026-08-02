"""Convert Jira wiki markup to Markdown.

Jira exports store comment/description bodies in Jira's wiki syntax. Radd stores
everything as Markdown, so the importer runs bodies through this first — and
`fix_jira_markup.py` back-fills already-imported rows.

KEEP IN LOCKSTEP with the frontend twin `web/src/lib/jira-markup.ts`: same rules,
same order. Handles: `[text|url]` / `[url]` links, `[~user]` mentions, `{quote}` /
`{panel}`, `{code}` / `{noformat}` blocks, `{{mono}}`, `hN.` headings, `||header||`
/ `|cell|` tables, `#` / nested `*#` lists, `*bold*`, `-struck-`, `{color}`
(stripped), `{anchor}` / `{toc}` (stripped), `!image.png!` embeds, and emoticons.

`assume_jira`: the importer converts unconditionally (the source is known Jira).
The back-fill passes ``assume_jira=False`` so rows are only touched when they carry
an unambiguous Jira construct — the ambiguous rules (bold, `#` lists, strike,
emoticons) would otherwise corrupt natively-authored Markdown (`*emphasis*`,
`# Heading`). Code/noformat blocks are stashed in a single pass (so one can't
swallow the other's placeholder) and protected from every inline rule.
"""

import re

# Code + noformat in ONE alternation so whichever block opens first consumes any
# markers nested inside it (correct Jira semantics + no interleaved placeholders).
_FENCED_RE = re.compile(
    r"\{code(?::(?P<lang>[^}]*))?\}(?P<cbody>.*?)\{code\}"
    r"|\{noformat(?::[^}]*)?\}(?P<nbody>.*?)\{noformat\}",
    re.DOTALL,
)
_PANEL_RE = re.compile(r"\{panel(?::([^}]*))?\}(.*?)\{panel\}", re.DOTALL)
_QUOTE_RE = re.compile(r"\{quote\}(.*?)\{quote\}", re.DOTALL)
_COLOR_RE = re.compile(r"\{color(?::[^}]*)?\}")
_ANCHOR_RE = re.compile(r"\{anchor:[^}]*\}")
_TOC_RE = re.compile(r"^\{toc[^}]*\}[ \t]*\n?", re.MULTILINE)
_MONO_RE = re.compile(r"\{\{(.+?)\}\}")
# [text|url] and [text|url|tip] — a link with a pipe (not a bare [KEY] or [~user]).
_LINK_RE = re.compile(r"\[([^\]|\n]+)\|([^\]|\n]+?)(?:\|[^\]\n]*)?\]")
# [https://…] — a bare bracketed URL (Jira renders it as a link) → an autolink.
_BARE_URL_RE = re.compile(r"\[((?:https?|mailto):[^\]\s|]+)\]")
_USER_RE = re.compile(r"\[~([\w.\-]+)\]")
_HEADING_RE = re.compile(r"^h([1-6])\.\s+", re.MULTILINE)
# `*bold*` → `**bold**`. Not adjacent to word chars / another `*`, and the content
# can't start/end with `*` or whitespace — so native `**strong**` (incl. our own
# panel-title output), mid-word stars and `* list` markers never match.
_BOLD_RE = re.compile(r"(?<![\w*\\])\*([^\s*](?:[^*\n]*?[^\s*])?)\*(?![\w*])")
# `-struck-` → `~~struck~~`. Whitespace-delimited, not digit-led, and the content
# can't start/end with `-` — so ranges ("-5-10"), `--flags`, `---` rules and table
# separator rows pass through.
_STRIKE_RE = re.compile(
    r"(?:^|(?<=\s))-(?!\d)([^\s-](?:[^-\n]*?[^\s-])?)-(?=$|[\s.,;:!?])", re.MULTILINE
)
# `!image.png!` / `!http://…!` embeds — only when the body looks like a file/URL.
_IMAGE_RE = re.compile(r"!([^!\s|]+)(?:\|[^!\n]*)?!")
_IMAGE_EXT_RE = re.compile(r"\.(?:png|jpe?g|gif|webp|svg|bmp)$", re.IGNORECASE)
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_LANG_RE = re.compile(r"(?:^|\|)language=([\w+-]+)")
_LIST_RE = re.compile(r"^([*#-]{1,6})[ \t]+(.*)$")
_TABLE_LINE_RE = re.compile(r"^\s*\|")
# Jira renders these as icons/emoji, so converting is faithful to what Jira showed.
_EMOTICONS = [
    ("(/)", "✅"),
    ("(x)", "❌"),
    ("(!)", "⚠️"),
    ("(?)", "❓"),
    ("(i)", "ℹ️"),
    ("(+)", "➕"),
    ("(-)", "➖"),
    ("(y)", "👍"),
    ("(n)", "👎"),
    (":D", "😄"),
    (":P", "😛"),
    (";)", "😉"),
    (":)", "🙂"),
    (":(", "🙁"),
]
_EMOTICON_MAP = dict(_EMOTICONS)
_EMOTICON_RE = re.compile(
    r"(?:^|(?<=\s))(?:"
    + "|".join(re.escape(token) for token, _ in _EMOTICONS)
    + r")(?=$|[\s.,;:!?])",
    re.MULTILINE,
)

# A quick gate: only touch text that actually looks like Jira markup. The ambiguous
# rules (bold, `#` lists, strike, emoticons) are safe to run *because* of this gate —
# a gated text is Jira-origin, where `# x` is a list item, never a Markdown heading.
_HAS_JIRA_RE = re.compile(
    r"\{code|\{noformat[:}]|\{quote\}|\{panel[:}]|\{color[:}]|\{anchor:|^\{toc"
    r"|\{\{|\[[^\]\n]*\||\[(?:https?|mailto):|\[~|^h[1-6]\.|^\s*\|\|[^|]"
    r"|!\S+\.(?:png|jpe?g|gif|webp|svg|bmp)(?:\|[^!\n]*)?!",
    re.MULTILINE,
)

# Private-use sentinel — never appears in real text, and (unlike NUL) is storable,
# so even a pathological un-restore can't crash the DB.
_SENT = chr(1)


def _clean_lang(params: str) -> str:
    """`{code:java}` and `{code:title=x|language=java}` both carry a language."""
    trimmed = params.strip()
    if "=" not in trimmed:
        return trimmed if re.fullmatch(r"[\w+-]*", trimmed) else ""
    match = _LANG_RE.search(trimmed)
    return match.group(1) if match else ""


def _panel_to_quote(match: re.Match[str]) -> str:
    params, body = match.group(1) or "", match.group(2)
    title_match = re.search(r"(?:^|\|)title=([^|}]*)", params)
    lines = ["> " + line for line in body.strip().split("\n")]
    if title_match and title_match.group(1).strip():
        lines = ["> **" + title_match.group(1).strip() + "**", ">"] + lines
    return "\n" + "\n".join(lines) + "\n"


def _split_cells(line: str) -> list[str]:
    """`||h1||h2||` / `|c1|c2|` — normalize a line's cells (`||` = header marker)."""
    inner = line.strip().replace("||", "|").removeprefix("|").removesuffix("|")
    return [cell.strip() for cell in inner.split("|")]


def _convert_lines(text: str) -> str:
    """Line-based pass: Jira tables → GFM tables, Jira `#`/nested lists → Markdown
    lists. Runs BEFORE the `hN.` heading rule so it never sees converted `# ` lines."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _TABLE_LINE_RE.match(line):
            rows: list[list[str]] = []
            while i < len(lines) and _TABLE_LINE_RE.match(lines[i]):
                rows.append(_split_cells(lines[i]))
                i += 1
            width = max(len(row) for row in rows)
            # GFM needs a header + separator; a blank line keeps it out of a paragraph.
            if out and out[-1].strip():
                out.append("")
            out.append("| " + " | ".join(rows[0]) + " |")
            out.append("|" + " --- |" * width)
            out.extend("| " + " | ".join(row) + " |" for row in rows[1:])
            continue
        # `# x` ordered, `* x`/`- x` bullets, `**`/`##`/mixed runs = nesting (last
        # char decides the type). Single `*`/`-` is already valid Markdown — leave it.
        list_match = _LIST_RE.match(line)
        if list_match and not (len(list_match.group(1)) == 1 and list_match.group(1) != "#"):
            markers, rest = list_match.group(1), list_match.group(2)
            marker = "1." if markers.endswith("#") else "-"
            out.append("    " * (len(markers) - 1) + marker + " " + rest)
            i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _image(match: re.Match[str]) -> str:
    src = match.group(1)
    if _URL_RE.match(src):
        return f"![]({src})"
    if _IMAGE_EXT_RE.search(src):
        return f"*(image: {src})*"  # attachment never imported
    return match.group(0)


def replace_attachment_embeds(text: str | None, urls: dict[str, str]) -> str:
    """Rewrite Jira `!filename.png|params!` embeds whose file WAS imported into real
    markdown images (`![name](url)`) — run on the RAW wiki text before
    jira_to_markdown, which leaves proper markdown images untouched. Unknown
    filenames keep the embed (the converter degrades them to a placeholder)."""
    if not text or not urls:
        return text or ""

    def swap(match: re.Match[str]) -> str:
        name = match.group(1)
        url = urls.get(name)
        return f"![{name}]({url})" if url else match.group(0)

    return _IMAGE_RE.sub(swap, text)


def jira_to_markdown(text: str | None, *, assume_jira: bool = True) -> str:
    if not text:
        return text or ""
    if not assume_jira and not _HAS_JIRA_RE.search(text):
        return text
    blocks: list[str] = []

    def stash(match: re.Match[str]) -> str:
        if match.group("cbody") is not None:
            lang = _clean_lang(match.group("lang") or "")
            fenced = f"```{lang}\n{match.group('cbody').strip(chr(10))}\n```"
        else:
            fenced = f"```\n{match.group('nbody').strip(chr(10))}\n```"
        blocks.append(fenced)
        return f"{_SENT}{len(blocks) - 1}{_SENT}"

    text = _FENCED_RE.sub(stash, text)
    text = _ANCHOR_RE.sub("", text)
    text = _TOC_RE.sub("", text)
    text = _PANEL_RE.sub(_panel_to_quote, text)
    text = _QUOTE_RE.sub(
        lambda m: "\n" + "\n".join("> " + ln for ln in m.group(1).strip().split("\n")) + "\n",
        text,
    )
    text = _COLOR_RE.sub("", text)
    text = _MONO_RE.sub(r"`\1`", text)
    text = _LINK_RE.sub(r"[\1](\2)", text)  # before tables: removes `|` from links
    text = _BARE_URL_RE.sub(r"<\1>", text)
    text = _USER_RE.sub(r"@\1", text)
    text = _convert_lines(text)
    text = _HEADING_RE.sub(lambda m: "#" * int(m.group(1)) + " ", text)
    text = _BOLD_RE.sub(r"**\1**", text)
    text = _STRIKE_RE.sub(r"~~\1~~", text)
    text = _EMOTICON_RE.sub(lambda m: _EMOTICON_MAP.get(m.group(0), m.group(0)), text)
    text = _IMAGE_RE.sub(_image, text)

    # Reverse order so a placeholder nested inside another block still resolves.
    for index in reversed(range(len(blocks))):
        text = text.replace(f"{_SENT}{index}{_SENT}", "\n" + blocks[index] + "\n")

    # Hard guard: never let a NUL or a stray sentinel reach storage.
    return text.replace("\x00", "").replace(_SENT, "")
