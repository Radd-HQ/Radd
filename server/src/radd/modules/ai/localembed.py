"""Built-in CPU embeddings (spec 101 addendum): the ai plugin ships its own
embedding backend, so semantic search needs NO external model server.

Backed by `fastembed` (Apache-2.0: ONNX Runtime + quantized models — no torch,
no GPU). Optional extra `radd[localembed]`; everything here degrades to
"unavailable" when it isn't installed. A provider row with wire shape LOCAL
carries only a model name; the embeddings role is the only role it can hold.

This is the zero-infra FALLBACK tier (~20 texts/s on a desktop CPU — fine for
small instances, not for bulk imports). Heavier corpora and GPUs belong to the
optional `embeddings` compose service (TEI), which Radd talks to as an ordinary
OpenAI-shape provider — docs/deploy.md.

Model weights download from Hugging Face on FIRST use into
RADD_LOCAL_EMBED_CACHE (pre-seed that directory on air-gapped deploys —
docs/deploy.md). Loading is seconds-slow, so instances are cached per model
and inference runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Sequence
from typing import Any

from radd.config import settings

from .types import AiConfigError

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"  # 384d, fastembed's own default

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


def _instance(model: str) -> Any:
    """The cached TextEmbedding for a model — creation downloads weights on
    first use, so it happens at most once per process per model."""
    from fastembed import TextEmbedding

    with _lock:
        cached = _models.get(model)
        if cached is None:
            logger.info("localembed: loading %s (downloads on first use)", model)
            cached = TextEmbedding(model_name=model, cache_dir=settings.ai_local_embed_cache)
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
        return [[float(v) for v in vector] for vector in instance.embed(list(texts))]

    return await asyncio.to_thread(_run)


async def probe(model: str) -> float:
    """Load + embed one string -> latency ms (the Test button for LOCAL rows;
    first run includes the model download, which is the honest number)."""
    started = time.monotonic()
    await embed_texts(model, ["ping"])
    return (time.monotonic() - started) * 1000.0
