"""The managed interpreter (RADD-1269): one uv-built virtual environment per
instance, under `settings.scripts_dir`, with the Radd SDK client installed
into it and whatever packages an admin asked for.

uv does the work. It is already in the image for the server's own install,
it can fetch a CPython the host does not have, and `uv pip` gives a resolver
that reports what it resolved. Everything here is a subprocess with a
timeout; nothing imports into the server process.

Where packages come from (RADD-1277): the WHEELHOUSES first — directories of
wheels uv reads from disk (`settings.scripts_find_links`, which the image
points at `/app/wheels` holding the SDK and its closure, plus
`<scripts_dir>/wheels` on the data volume for an operator's own) — then the
package index the admin named on Settings → Scripts, else PyPI. The build of
the venv itself never touches the network when the SDK is in a wheelhouse:
that is what lets an air-gapped instance build it at all, since the image
sets `UV_NO_CACHE` and a dropped route hangs uv rather than refusing it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from radd.config import settings

logger = logging.getLogger(__name__)

#: How much of a tool's output a row keeps.
LOG_TAIL = 4000

#: The operator's wheelhouse, under `scripts_dir` (the data volume).
WHEELHOUSE_DIR = "wheels"


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str  # stdout + stderr, tail-capped
    returncode: int


def root() -> Path:
    # ABSOLUTE: the child runs with its own cwd (the run directory), so a
    # relative `var/scripts` would be looked up from there and never found.
    return Path(settings.scripts_dir).resolve()


def venv_dir() -> Path:
    return root() / "venv"


def python_path() -> Path:
    """The venv's interpreter, on either platform's layout."""
    windows = venv_dir() / "Scripts" / "python.exe"
    return windows if windows.exists() else venv_dir() / "bin" / "python"


def ready() -> bool:
    return python_path().exists()


def wheelhouses() -> list[Path]:
    """The wheel directories that EXIST, in resolution order: the configured
    ones (the image's), then the operator's on the data volume."""
    named = [Path(part.strip()).resolve() for part in settings.scripts_find_links.split(",") if part.strip()]
    return [path for path in [*named, root() / WHEELHOUSE_DIR] if path.is_dir()]


def sdk_wheel() -> Path | None:
    """The newest `radd_sdk` wheel in any wheelhouse, or None."""
    found = sorted(
        (wheel for house in wheelhouses() for wheel in house.glob("radd_sdk-*.whl")),
        key=lambda wheel: wheel.name,
    )
    return found[-1] if found else None


def sdk_source() -> str:
    """Where the Radd SDK client is installed FROM: an explicit setting, else
    a wheel from a wheelhouse, else the repository's `sdk/` when this is a
    checkout, else the package name."""
    if settings.scripts_sdk_source:
        return settings.scripts_sdk_source
    wheel = sdk_wheel()
    if wheel is not None:
        return str(wheel)
    checkout = Path(__file__).resolve().parents[5] / "sdk"
    if (checkout / "pyproject.toml").exists():
        return str(checkout)
    return "radd-sdk"


def sdk_is_bundled() -> bool:
    """True when the SDK installs from a wheel (no build backend, and its
    closure is beside it) — the case in which the build runs offline."""
    return sdk_source().endswith(".whl")


def masked_url(url: str) -> str:
    """The index URL with any password hidden — for a read model or a log."""
    parts = urlsplit(url)
    if not parts.password:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    netloc = f"{parts.username}:***@{host}" if parts.username else f"***@{host}"
    return urlunsplit(parts._replace(netloc=netloc))


def resolver_args(index_url: str = "", offline: bool = False) -> list[str]:
    """The `uv pip` flags that say where packages come from: every wheelhouse,
    the admin's index when named, `--offline` when asked (uv then reads
    wheelhouses and nothing else, and says so instead of waiting on a route)."""
    args: list[str] = []
    for house in wheelhouses():
        args += ["--find-links", str(house)]
    if index_url:
        args += ["--index-url", index_url]
    if offline:
        args.append("--offline")
    return args


async def _run(*args: str, timeout: float | None = None) -> ToolResult:
    """Run uv (or any tool) and capture its output, tail-capped."""
    # Copy, never hardlink: the wheelhouse (the image layer) and the venv (the
    # data volume) are different filesystems in every deployment, and uv's
    # fallback warning would otherwise head every rebuild log.
    env = {"UV_LINK_MODE": "copy", **os.environ, "UV_NO_PROGRESS": "1"}
    # The server's own `UV_PYTHON` pin (the image sets it) must not leak into
    # a venv built for a different version.
    env.pop("UV_PYTHON", None)
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
    except FileNotFoundError as exc:
        return ToolResult(False, f"{args[0]}: not found ({exc})", 127)
    try:
        out, _ = await asyncio.wait_for(
            process.communicate(), timeout=timeout or settings.scripts_tool_timeout_seconds
        )
    except TimeoutError:
        process.kill()
        return ToolResult(False, f"{' '.join(args[:3])}… exceeded {settings.scripts_tool_timeout_seconds}s", -1)
    text = out.decode(errors="replace")
    return ToolResult(process.returncode == 0, text[-LOG_TAIL:], process.returncode or 0)


async def available_versions() -> list[str]:
    """What `uv python list` can provide here — for the picker. Best effort:
    an empty list when uv cannot say, never an exception on a settings page."""
    result = await _run(settings.scripts_uv_path, "python", "list", "--only-installed", timeout=30)
    versions: list[str] = []
    if not result.ok:
        return versions
    for line in result.output.splitlines():
        head = line.split()[0] if line.split() else ""
        if head.startswith("cpython-"):
            version = head.removeprefix("cpython-").split("-", 1)[0].split("+", 1)[0]
            short = ".".join(version.split(".")[:2])
            if short not in versions:
                versions.append(short)
    return versions


async def rebuild(python_version: str, *, index_url: str = "", offline: bool = False) -> ToolResult:
    """(Re)create the venv for `python_version` and install the SDK into it.

    Destructive and deliberate: a rebuild is how an admin changes the Python
    version, and a venv built for 3.11 cannot be talked into 3.12 in place.
    The packages table is the record of what to reinstall afterwards; the
    caller does that.

    No `--seed`: pip comes from an index, and nothing the harness runs needs
    it. The SDK installs OFFLINE whenever it is a bundled wheel, so the build
    is the same on a laptop and behind an air gap."""
    root().mkdir(parents=True, exist_ok=True)
    if venv_dir().exists():
        shutil.rmtree(venv_dir(), ignore_errors=True)
    made = await _run(settings.scripts_uv_path, "venv", "--python", python_version, str(venv_dir()))
    if not made.ok:
        return made
    sdk = await install(sdk_source(), index_url=index_url, offline=offline or sdk_is_bundled())
    if not sdk.ok:
        return ToolResult(False, made.output + "\n" + sdk.output, sdk.returncode)
    probe = await _run(str(python_path()), "-c", "import sys; print(sys.version.split()[0])", timeout=30)
    return ToolResult(probe.ok, (made.output + "\n" + sdk.output + "\n" + probe.output)[-LOG_TAIL:], probe.returncode)


async def resolved_python() -> str:
    if not ready():
        return ""
    probe = await _run(str(python_path()), "-c", "import sys; print(sys.version.split()[0])", timeout=30)
    return probe.output.strip().splitlines()[-1] if probe.ok and probe.output.strip() else ""


async def install(spec: str, *, index_url: str = "", offline: bool = False) -> ToolResult:
    if not ready():
        return ToolResult(False, "the interpreter is not built yet", 1)
    return await _run(
        settings.scripts_uv_path, "pip", "install", "--python", str(python_path()),
        *resolver_args(index_url, offline), spec,
    )


async def uninstall(name: str) -> ToolResult:
    if not ready():
        return ToolResult(False, "the interpreter is not built yet", 1)
    return await _run(settings.scripts_uv_path, "pip", "uninstall", "--python", str(python_path()), name)


async def installed_version(name: str) -> str:
    """What resolved for `name`, from `uv pip show`; "" when it is not there."""
    if not ready():
        return ""
    result = await _run(settings.scripts_uv_path, "pip", "show", "--python", str(python_path()), name, timeout=60)
    if not result.ok:
        return ""
    for line in result.output.splitlines():
        if line.lower().startswith("version:"):
            return line.split(":", 1)[1].strip()
    return ""


def fallback_python() -> str:
    """The interpreter a test may substitute for the venv: this process's own.
    Named so a test can say what it is doing rather than reaching into
    `sys`."""
    return sys.executable
