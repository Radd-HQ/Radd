"""Vocabulary of the scripts plugin (RADD-1269)."""

from enum import StrEnum


class ScriptEntity(StrEnum):
    PACKAGE = "script_package"
    INTERPRETER = "script_interpreter"


class ScriptEvent(StrEnum):
    PACKAGE_INSTALLED = "script_package.installed"
    PACKAGE_REMOVED = "script_package.removed"
    INTERPRETER_REBUILT = "script_interpreter.rebuilt"
    INTERPRETER_UPDATED = "script_interpreter.updated"


class PackageStatus(StrEnum):
    PENDING = "pending"
    INSTALLED = "installed"
    FAILED = "failed"


class InterpreterStatus(StrEnum):
    MISSING = "missing"  # no venv yet
    READY = "ready"
    FAILED = "failed"


#: The RBAC atom for everything on Settings → Scripts and for placing a script
#: node in an automation. Implied by global management.
PERM_MANAGE = "script.manage"

#: The automation node keys.
NODE_RUN = "script.run"
NODE_DECIDE = "script.decide"

#: What the child process prints on its LAST stdout line, followed by JSON.
RESULT_SENTINEL = "__RADD_RESULT__"

#: The fallback port of a deciding script — taken when the script fails, times
#: out, or names a port it did not declare.
UNAVAILABLE_PORT = "unavailable"

#: Name of the bundled harness module and the user's module inside the run dir.
HARNESS_FILE = "_radd_harness.py"
SCRIPT_FILE = "radd_script.py"

#: The author contract — the body a freshly dropped node arrives with
#: (RADD-1272: the script LIVES on the node, so the contract is its default).
STARTER_SCRIPT = '''"""A Radd script. `main` receives the run's context and returns a value.

    ctx.event        the event that fired (type, actor, payload) — None on a manual/scheduled run
    ctx.items        the issues this node is acting on, as full read models (list of dicts)
    ctx.vars         values upstream nodes produced: ctx.vars["triage"]["priority"]
    ctx.params       this node's own params
    ctx.client       a ready radd_sdk.RaddClient, acting as the automation's identity
    ctx.log(text)    write a line to the run's stderr (shown in the run report)

For a "Run a script" node, return a dict: each key you declared as an output
becomes a {{name.key}} token downstream. For a "Decide with a script" node,
return the name of the port to take.
"""


def main(ctx):
    for item in ctx.items:
        ctx.log(f"saw {item['key']}: {item['title']}")
    return {"count": len(ctx.items)}
'''
