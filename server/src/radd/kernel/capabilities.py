"""Capability evaluation — the read side of the /capabilities aggregator (§3.2, §8a).

A plugin declares a `CapabilitySpec` (static `enabled`, or a `check()` returning
`{enabled: bool, **detail}`) in its manifest; the kernel evaluates them all here.
This is the inversion of the hardcoded provider `enabled()` logic that `/instance/
status` inlined — the truth about each provider now lives in its own plugin.
"""

from __future__ import annotations

from typing import Any

from .registry import registries
from .specs import CapabilitySpec


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
        except Exception:  # a broken check must not blank the whole surface
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
    """`{key: {enabled, category, **detail}}` — for consumers that look up a
    specific capability (e.g. the legacy /instance/status adapter)."""
    return {
        c["key"]: {"enabled": c["enabled"], "category": c["category"], **c["detail"]}
        for c in evaluate()
    }
