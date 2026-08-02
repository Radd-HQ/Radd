"""Feature detection + adaptation for the pages module's service (spec 43).

The doc tools (`get_page`/`search_docs`) exist only when the pages module is
enabled in `settings.modules` AND its service exposes the functions we need — a
stub or absent module simply omits them. Detection is resolved per call, never
cached, so a parallel-built pages module lights the tools up without a restart.
The binding is tolerant of the exact signature the docs service ships
(parameters are matched by name).
"""

import importlib
import inspect
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User

from .types import PAGES_MODULE_PATH

_PAGE_GET_FUNCTIONS = ("get_page",)
_PAGE_SEARCH_FUNCTIONS = ("search_pages", "search")


def pages_functions() -> tuple[Callable[..., Any], Callable[..., Any]] | None:
    """(get_page, search) from the docs service, or None while the module is
    disabled, absent, or still a stub."""
    if PAGES_MODULE_PATH not in settings.modules:
        return None
    # The pages module keeps FTS in its own `search` submodule; probe both.
    sources = []
    for submodule in ("service", "search"):
        try:
            sources.append(importlib.import_module(f"{PAGES_MODULE_PATH}.{submodule}"))
        except Exception:
            continue

    def _find(names: tuple[str, ...]) -> Callable[..., Any] | None:
        for source in sources:
            for name in names:
                fn = getattr(source, name, None)
                if callable(fn):
                    return fn
        return None

    get_page = _find(_PAGE_GET_FUNCTIONS)
    search = _find(_PAGE_SEARCH_FUNCTIONS)
    if get_page is None or search is None:
        return None
    return get_page, search


def pages_available() -> bool:
    return pages_functions() is not None


async def call_pages(
    fn: Callable[..., Any], session: AsyncSession, actor: User, **values: Any
) -> Any:
    """Bind (session, actor, **values) onto the docs function by parameter name."""
    kwargs: dict[str, Any] = {}
    for name in inspect.signature(fn).parameters:
        if name == "session":
            kwargs[name] = session
        elif name in ("actor", "user"):
            kwargs[name] = actor
        elif name in values:
            kwargs[name] = values[name]
    try:
        result = fn(**kwargs)
    except TypeError as exc:
        raise ConflictError("docs", reason=f"docs service signature mismatch: {exc}") from None
    if inspect.isawaitable(result):
        result = await result
    return result


def jsonable(value: Any) -> Any:
    """Best-effort JSON projection of whatever the docs service returns."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__table__"):  # SQLAlchemy row
        return {c.name: jsonable(getattr(value, c.name)) for c in value.__table__.columns}
    return str(value)  # uuid, datetime, enums, ...
