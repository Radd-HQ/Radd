"""The per-field judgement behind the inbound profile — PURE. Jira returns each
issue's `fields` as `{field_id: value}`, the value's shape depending on the field's
type (scalar, `{value|name}` option, array, user, date string). These decide how
to render a value, which Radd type a field resembles, and which band it falls in.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from . import schemakeys
from .types import (
    DOMINANCE_NOISE,
    DOMINANCE_NOISE_REASON,
    FieldBand,
    InferredType,
)

# A field whose distinct scalar values stay under this many across the sample is
# offered as a SELECT; more distinct values than this reads as free text.
SELECT_MAX_DISTINCT = 50
MAX_SAMPLES = 5  # example values surfaced per field


def band_of(
    schema_key: str, is_builtin: bool, populated: int, examined: int, dominant_ratio: float
) -> tuple[FieldBand, str]:
    """Which band a field belongs in, and WHY — the reason is shown verbatim.

    A reason rather than a bare flag, because everything outside IN_USE is
    collapsed AND defaulted to `ignore`: "no values on any of the 126 issues" or
    "Jira board ordering key" turns a hidden field into a decision you can
    disagree with, rather than one that silently vanished.

    UNUSED is checked FIRST and is purely a count — a field nothing fills in has
    nothing to import, whatever it is called. The other two signals are equally
    instance-independent: Jira's own stable type key, and the shape of the data.
    """
    if is_builtin:
        return FieldBand.BUILTIN, "handled natively — no mapping needed"
    if populated == 0:
        # Honest about the evidence: over a full snapshot this is a fact; over a
        # sample it is only "not in the N we looked at", and the admin can expand
        # the section and map it anyway.
        scope = f"any of the {examined} issues" if examined else "any issue"
        return FieldBand.UNUSED, f"no values on {scope}"
    keyed = schemakeys.noise_reason(schema_key)
    if keyed:
        return FieldBand.NOISE, keyed
    if dominant_ratio >= DOMINANCE_NOISE:
        return FieldBand.NOISE, DOMINANCE_NOISE_REASON
    return FieldBand.IN_USE, ""


def render_value(value: Any) -> str | None:
    """One Jira field value → a display string, or None when empty. Handles the
    shapes Jira uses: option objects, user objects, arrays, scalars."""
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, dict):
        # Option ({value}/{name}), user ({displayName/name}), or status ({name}).
        for key in ("value", "name", "displayName", "key"):
            if value.get(key):
                return str(value[key])
        return None
    if isinstance(value, list):
        rendered = [render_value(v) for v in value]
        kept = [r for r in rendered if r]
        return ", ".join(kept) if kept else None
    return str(value)


def scalar_values(value: Any) -> list[str]:
    """The distinct scalar tokens a value contributes (an array contributes each
    element) — feeds the SELECT option-set detection."""
    if isinstance(value, list):
        out: list[str] = []
        for element in value:
            out.extend(scalar_values(element))
        return out
    rendered = render_value(value)
    return [rendered] if rendered is not None else []


def classify(
    schema_type: str, schema_items: str, is_array: bool, distinct: Counter[str]
) -> InferredType:
    """Map a Jira field's catalog type to a coarse Radd type.

    The catalog is AUTHORITATIVE when it names a type — a Jira `string` is text
    even if the small sample happened to show few distinct values, and an
    `option` is a select even if the sample only caught one. Cardinality is used
    only as a fallback when Jira gives us no type (schema_type empty), which is
    where the sample is the only signal we have.
    """
    jira = schema_type.lower()
    items = schema_items.lower()
    if jira in ("date", "datetime"):
        return InferredType.DATE
    if jira in ("number",):
        return InferredType.NUMBER
    if jira == "user" or items == "user":
        return InferredType.USER
    if jira == "option-with-child":
        return InferredType.SELECT
    if jira == "array" or is_array:
        if items == "option":
            return InferredType.MULTI_SELECT
        if items in ("string", "user", "component", "version"):
            # labels/components/versions — high-cardinality arrays → text.
            return InferredType.TEXT
        # Unknown array element type: let the sample decide select-vs-text.
        return (
            InferredType.MULTI_SELECT
            if 0 < len(distinct) <= SELECT_MAX_DISTINCT
            else InferredType.TEXT
        )
    if jira == "option":
        return InferredType.SELECT
    if jira in ("string", "any"):
        return InferredType.TEXT
    if jira:
        # A named Jira type we don't special-case (priority, resolution, …) —
        # scalar with a bounded value set, so a select is the safe default.
        return InferredType.SELECT
    # No catalog type at all: the sample's cardinality is the only signal.
    if not distinct:
        return InferredType.UNKNOWN
    return InferredType.SELECT if len(distinct) <= SELECT_MAX_DISTINCT else InferredType.TEXT
