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

#: Texts per ONNX forward pass (RADD-724). The CALLER's batch is tuned for a GPU
#: model server — `ai_embed_batch` defaults to 256 — and ONNX activations for
#: that many sequences are gigabytes, which OOM-killed the worker within seconds
#: of the model finally loading. The in-process backend chunks to a size a CPU
#: can hold regardless of what it is handed; throughput barely changes, because
#: CPU inference is compute-bound rather than batch-bound.
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
    """A writable directory for downloaded weights (RADD-722).

    The configured path is RESOLVED and created here rather than handed to
    fastembed as-is. The default is relative, and in the container the working
    directory belongs to root while the process runs as an unprivileged user —
    so `var/models` raised PermissionError on every single iteration and the
    built-in backend could never work in the shipped image.

    A model cache is an optimisation. Being unable to write one must degrade to
    "download again next boot", never to a crash loop — so an unusable path
    falls back to a temp dir with a warning.
    """
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
