"""Running one script once (RADD-1269): a subprocess of the managed
interpreter, the packet on stdin, the result on the last stdout line.

Out of process on purpose — crash isolation and package isolation are the
whole argument for a separate interpreter. The run directory is a fresh
temporary directory holding the bundled harness and the script body; the
environment carries the Radd URL and a short-lived token the caller minted for
the automation's identity; stdout and stderr are captured, tail-capped, and
the process is killed at the timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from radd.config import settings

from . import interpreter
from .types import HARNESS_FILE, RESULT_SENTINEL, SCRIPT_FILE

logger = logging.getLogger(__name__)

#: How much captured output a run keeps.
OUTPUT_TAIL = 8000


@dataclass(frozen=True)
class Outcome:
    ok: bool
    result: Any = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    duration_ms: int = 0

    @property
    def summary(self) -> str:
        """One line for a plan detail or a log."""
        if self.ok:
            return f"ok in {self.duration_ms} ms"
        last = (self.stderr.strip().splitlines() or [""])[-1]
        return f"{self.error or 'failed'}{': ' + last if last and last != self.error else ''}"


def _harness_source() -> str:
    return (Path(__file__).parent / "harness.py").read_text()


async def run(
    body: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    python: str | None = None,
) -> Outcome:
    """Execute `body` once. `python` overrides the managed interpreter — the
    tests use this process's own, so the contract is proven without uv."""
    executable = python or (str(interpreter.python_path()) if interpreter.ready() else "")
    if not executable:
        return Outcome(False, error="the script interpreter is not built (Settings → Scripts)")
    timeout = max(1.0, min(float(timeout), float(settings.scripts_max_timeout_seconds)))
    run_dir = Path(tempfile.mkdtemp(prefix="radd-script-", dir=settings.scripts_run_dir or None))
    started = monotonic()
    try:
        (run_dir / HARNESS_FILE).write_text(_harness_source())
        (run_dir / SCRIPT_FILE).write_text(body)
        env = {
            # A minimal environment: the child must not inherit the server's
            # database URL, secrets or session keys. What it gets is the
            # interpreter, a locale, and the Radd API it was handed.
            "PATH": os.environ.get("PATH", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "HOME": str(run_dir),
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "RADD_URL": str(payload.get("radd_url") or ""),
        }
        process = await asyncio.create_subprocess_exec(
            executable,
            str(run_dir / HARNESS_FILE),
            cwd=run_dir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdin = json.dumps(payload, default=str).encode()
        try:
            out, err = await asyncio.wait_for(process.communicate(stdin), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            return Outcome(
                False,
                error=f"timed out after {timeout:g}s",
                duration_ms=int((monotonic() - started) * 1000),
            )
        stdout = out.decode(errors="replace")
        stderr = err.decode(errors="replace")[-OUTPUT_TAIL:]
        duration = int((monotonic() - started) * 1000)
        if process.returncode != 0:
            last = (stderr.strip().splitlines() or ["(no output)"])[-1]
            return Outcome(False, stdout=stdout[-OUTPUT_TAIL:], stderr=stderr, error=last, duration_ms=duration)
        result, rest = _split_result(stdout)
        if result is None and RESULT_SENTINEL not in stdout:
            return Outcome(
                False, stdout=rest[-OUTPUT_TAIL:], stderr=stderr,
                error="the script produced no result (did main return?)", duration_ms=duration,
            )
        return Outcome(True, result=result, stdout=rest[-OUTPUT_TAIL:], stderr=stderr, duration_ms=duration)
    except FileNotFoundError as exc:
        return Outcome(False, error=f"interpreter not found: {exc}")
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def _split_result(stdout: str) -> tuple[Any, str]:
    """The JSON after the sentinel on the last line, and everything before it."""
    lines = stdout.rstrip("\n").split("\n")
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index]
        if line.startswith(RESULT_SENTINEL):
            try:
                parsed = json.loads(line[len(RESULT_SENTINEL):])
            except ValueError:
                return None, stdout
            return parsed.get("result"), "\n".join(lines[:index])
    return None, stdout
