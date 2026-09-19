"""The child-side program (RADD-1269). Copied VERBATIM into the run directory
and executed by the managed interpreter — never imported by the server, so it
must not import anything from `radd`.

Contract with the parent:

* stdin carries one JSON document: `{"event", "items", "vars", "params",
  "subject_ids", "actor", "radd_url", "radd_token"}`.
* the user's module is `radd_script.py` beside this file and defines
  `main(ctx)`;
* whatever `main` returns is printed on the LAST stdout line after the
  sentinel, JSON-encoded (`default=str`, so a date does not crash a run);
* an exception prints its traceback to stderr and exits 1.

`ctx.client` is a `radd_sdk.RaddClient` bound to the parent's URL and the
short-lived token the parent minted for this run. It is built lazily, so a
script that never touches the API never opens a connection.
"""

import importlib.util
import json
import os
import sys
import traceback

SENTINEL = "__RADD_RESULT__"


class Context:
    def __init__(self, payload):
        self.event = payload.get("event")
        self.items = payload.get("items") or []
        self.vars = payload.get("vars") or {}
        self.params = payload.get("params") or {}
        self.subject_ids = payload.get("subject_ids") or []
        self.actor = payload.get("actor") or {}
        self._url = payload.get("radd_url") or ""
        self._token = payload.get("radd_token") or ""
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not self._url or not self._token:
                raise RuntimeError("no Radd API is available to this run")
            from radd_sdk import RaddClient

            self._client = RaddClient(self._url, self._token)
        return self._client

    @property
    def item(self):
        """The first item, for the per-item case — None on an empty packet."""
        return self.items[0] if self.items else None

    def log(self, text):
        sys.stderr.write(str(text) + "\n")
        sys.stderr.flush()


def _load_script():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "radd_script.py")
    spec = importlib.util.spec_from_file_location("radd_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    main = getattr(module, "main", None)
    if not callable(main):
        raise RuntimeError("the script defines no main(ctx) function")
    return main


def run():
    payload = json.load(sys.stdin)
    ctx = Context(payload)
    try:
        main = _load_script()
        result = main(ctx)
    except SystemExit:
        raise
    except BaseException:  # the traceback IS the report: printed to stderr, which the parent shows in the run
        traceback.print_exc()
        return 1
    finally:
        if ctx._client is not None:
            try:
                ctx._client.close()
            except Exception:  # closing the client is best-effort: the process is about to exit anyway
                pass
    sys.stdout.write("\n" + SENTINEL + json.dumps({"result": result}, default=str) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(run())
