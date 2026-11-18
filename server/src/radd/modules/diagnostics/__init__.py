"""What the browser saw go wrong (RADD-1528).

Without this a crash in the SPA is visible only to the person it happened to.
This module is the receiving end — one route that turns a report into one
structured log line. It stores nothing: the log is
where an operator already looks, and a table of stack traces is a retention
question nobody has asked for.

Core, because reporting has to work precisely when something optional is broken.
"""

from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="diagnostics",
    description="Receives the browser's error reports and writes them to the server log.",
    depends_on=("auth",),
    routers=(router,),
)
