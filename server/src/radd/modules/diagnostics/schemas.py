from pydantic import BaseModel, Field

from radd.config import settings

_TEXT = settings.client_error_max_chars


class ClientErrorReport(BaseModel):
    """One error as the browser saw it. Every field is bounded: this route is
    reachable before sign-in, so its input is whatever anyone cares to send."""

    message: str = Field(min_length=1, max_length=500)
    stack: str = Field(default="", max_length=_TEXT)
    #: The SPA route, path only — the client strips the query string, which can carry search text.
    route: str = Field(default="", max_length=300)
    #: Which hook caught it: a render boundary, `window.onerror`, a rejected promise, a plugin slot.
    source: str = Field(default="", max_length=40)
    #: The plugin whose contribution threw, when a slot boundary caught it.
    plugin: str = Field(default="", max_length=100)
    #: The build the tab is running — a stale tab reports the version it was loaded with.
    build: str = Field(default="", max_length=40)
