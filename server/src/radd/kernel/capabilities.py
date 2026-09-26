"""Capability evaluation — the read side of `/capabilities`: each plugin's `CapabilitySpec`
(static `enabled`, or `check()` returning `{enabled, **detail}`) evaluated here."""

from __future__ import annotations

import logging
from typing import Any

from .registry import registries
from .specs import CapabilitySpec

logger = logging.getLogger(__name__)


def describe(cap: CapabilitySpec) -> dict[str, Any]:
    """One capability -> its serializable descriptor. Shared by `evaluate()`
    and the plugin manager, which reports a plugin's capabilities whether or
    not the plugin is currently loaded into the registry (a disabled connector
    still shows its configured/unconfigured state)."""
    enabled = cap.enabled
    detail: dict[str, Any] = {}
    if cap.check is not None:
        try:
            res = cap.check() or {}
            enabled = bool(res.get("enabled", enabled))
            detail = {k: v for k, v in res.items() if k != "enabled"}
        except Exception:  # never blank the surface; log it, or it reads "unconfigured" (RADD-898)
            logger.warning("capability %s check failed", cap.key, exc_info=True)
            enabled = False
            detail = {"error": "check failed"}
    return {
        "key": cap.key,
        "label": cap.label,
        "category": cap.category,
        "enabled": enabled,
        "detail": detail,
    }


def evaluate() -> list[dict[str, Any]]:
    """Evaluate every registered capability into a serializable descriptor list."""
    return [describe(cap) for cap in registries.capabilities.values()]


def capability_map() -> dict[str, dict[str, Any]]:
    """`{key: {enabled, category, **detail}}` — for consumers that look up one capability."""
    return {
        c["key"]: {"enabled": c["enabled"], "category": c["category"], **c["detail"]}
        for c in evaluate()
    }
