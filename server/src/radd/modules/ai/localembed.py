"""Built-in CPU embeddings (`fastembed`/ONNX, extra `radd[localembed]`): semantic
search with no model server. A LOCAL provider holds only a model name and only
the embeddings role. ~20 texts/s on a desktop CPU; bigger corpora belong on TEI
(docs/deploy.md). Weights download on first use into RADD_AI_LOCAL_EMBED_CACHE
(pre-seed it air-gapped); instances are cached per model, inference runs in a thread.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from radd.config import settings

from .types import AiConfigError

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"  # 384d, fastembed's own default

#: Texts per ONNX pass. The caller's batch (`ai_embed_batch`, 256) is GPU-sized and
#: OOM-killed the worker on CPU (RADD-724).
LOCAL_BATCH = 32

_models: dict[str, Any] = {}
_lock = threading.Lock()


def available() -> bool:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return True


def supported_models() -> list[dict[str, Any]]:
    """[{model, dim, description}] for the Settings model picker ([] when the
    extra isn't installed)."""
    if not available():
        return []
    from fastembed import TextEmbedding

    return [
        {
            "model": entry["model"],
            "dim": entry["dim"],
            "description": entry.get("description", ""),
        }
        for entry in TextEmbedding.list_supported_models()
    ]


def cache_dir() -> str:
    """A writable weights directory. The default is relative and the container's
    cwd is root-owned (RADD-722), so an unwritable path falls back to a temp dir
    with a warning — a cache miss, never a crash loop."""
    configured = Path(settings.ai_local_embed_cache).expanduser()
    try:
        configured.mkdir(parents=True, exist_ok=True)
        probe = configured / ".write-test"
        probe.touch()
        probe.unlink()
        return str(configured)
    except OSError as exc:
        fallback = Path(tempfile.gettempdir()) / "radd-localembed"
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning(
            "localembed: cache %s is not writable (%s); using %s — weights will be "
            "re-downloaded after a restart. Set RADD_AI_LOCAL_EMBED_CACHE to a "
            "writable path to keep them.",
            configured,
            exc,
            fallback,
        )
        return str(fallback)


def _instance(model: str) -> Any:
    """The cached TextEmbedding for a model — creation downloads weights on
    first use, so it happens at most once per process per model."""
    from fastembed import TextEmbedding

    with _lock:
        cached = _models.get(model)
        if cached is None:
            logger.info("localembed: loading %s (downloads on first use)", model)
            cached = TextEmbedding(model_name=model, cache_dir=cache_dir())
            _models[model] = cached
    return cached


async def embed_texts(model: str, texts: Sequence[str]) -> list[list[float]]:
    """Vectors for `texts`, input-ordered — the local twin of the /embeddings
    call. AiConfigError when the extra isn't installed (a clean 422, since the
    only way here is an admin-created LOCAL provider)."""
    if not available():
        raise AiConfigError(
            "built-in embeddings need the localembed extra (pip install 'radd[localembed]')"
        )
    name = model or DEFAULT_LOCAL_MODEL

    def _run() -> list[list[float]]:
        instance = _instance(name)
        ordered = list(texts)
        vectors: list[list[float]] = []
        for start in range(0, len(ordered), LOCAL_BATCH):
            chunk = ordered[start : start + LOCAL_BATCH]
            vectors.extend([float(v) for v in vector] for vector in instance.embed(chunk))
        return vectors

    return await asyncio.to_thread(_run)


async def probe(model: str) -> float:
    """Load + embed one string -> latency ms (the Test button for LOCAL rows;
    first run includes the model download, which is the honest number)."""
    started = time.monotonic()
    await embed_texts(model, ["ping"])
    return (time.monotonic() - started) * 1000.0
