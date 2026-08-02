"""Pure canned-response variable substitution (spec 66).

Same `{{token}}` regex idiom as automations/templating: the fixed token set
(`CannedToken` in types.py) arrives pre-resolved in `ctx`. Unknown tokens AND
tokens whose ctx value is missing or empty (e.g. no assignee on the item) render
verbatim — visible in the composer, debuggable, never an error.
"""

import re

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def render_canned(body: str, ctx: dict[str, str]) -> str:
    """Substitute `{{token}}` occurrences from `ctx`; unresolved tokens stay verbatim."""

    def replace(match: re.Match[str]) -> str:
        value = ctx.get(match.group(1))
        return match.group(0) if not value else value

    return _TOKEN_RE.sub(replace, body)
