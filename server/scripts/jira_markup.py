"""Jira wiki markup → Markdown — shim.

The CANONICAL converter now lives in the server module
`radd.modules.jiraimport.markup`, so the Jira import wizard and the CLI scripts
share one backend implementation (spec 90 relocated it there). This module stays
as the scripts' import point (`from jira_markup import …`) and re-exports it.

KEEP IN LOCKSTEP with the frontend twin `web/src/lib/jira-markup.ts`.
"""

from radd.modules.jiraimport.markup import (  # noqa: F401
    jira_to_markdown,
    replace_attachment_embeds,
)
