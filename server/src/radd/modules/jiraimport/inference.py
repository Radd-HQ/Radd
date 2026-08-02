"""Turn a page of Jira issues into an inbound schema (spec 90) — PURE, so it is
unit-tested without a live Jira.

Jira `/search` returns each issue's `fields` as `{field_id: value}`, where the
value shape depends on the field's Jira type: a scalar, a `{value|name}` option
object, an array of those, a user object, a date string. This walks a sample of
issues, and for every field id decides:

  - does it carry data often enough to be worth importing (populate rate),
  - what Radd type it most resembles (the create-default the wizard proposes),
  - and, for anything option-like, the distinct value set (the select options).

It never talks to the network and never guesses beyond the sample — the wizard
shows the guess and the admin has the final say.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from . import schemakeys
from .types import (
    BUILTIN_JIRA_FIELDS,
    DOMINANCE_NOISE,
    DOMINANCE_NOISE_REASON,
    FIELD_BAND_ORDER,
    FieldBand,
    InferredField,
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


def infer_schema(
    issues: list[dict[str, Any]], catalog: dict[str, dict[str, Any]]
) -> list[InferredField]:
    """Sample issues × the Jira field catalog → one InferredField per field seen.

    Built-in fields (summary/status/assignee/…) are flagged, not dropped: the
    wizard needs to show they are handled natively rather than leave the admin
    wondering where 'status' went.
    """
    sample_count = len(issues)
    populated: Counter[str] = Counter()
    array_seen: dict[str, bool] = {}
    samples: dict[str, list[str]] = {}
    distinct: dict[str, Counter[str]] = {}

    for issue in issues:
        fields = issue.get("fields") or {}
        for fid, value in fields.items():
            rendered = render_value(value)
            if rendered is None:
                continue
            populated[fid] += 1
            array_seen[fid] = array_seen.get(fid, False) or isinstance(value, list)
            bucket = samples.setdefault(fid, [])
            if len(bucket) < MAX_SAMPLES and rendered not in bucket:
                bucket.append(rendered)
            counter = distinct.setdefault(fid, Counter())
            for token in scalar_values(value):
                counter[token] += 1

    # Include every field the sample touched, plus every populated catalog field.
    seen_ids = set(populated) | {fid for issue in issues for fid in (issue.get("fields") or {})}
    results: list[InferredField] = []
    for fid in sorted(seen_ids):
        meta = catalog.get(fid, {})
        counter = distinct.get(fid, Counter())
        inferred = classify(
            meta.get("schema_type", ""),
            meta.get("schema_items", ""),
            array_seen.get(fid, False),
            counter,
        )
        name = meta.get("name", fid)
        is_builtin = fid in BUILTIN_JIRA_FIELDS and not meta.get("is_custom", False)
        # Only offer an option set when it is bounded — a "select" whose sample
        # already shows >SELECT_MAX_DISTINCT values is really text the catalog
        # mislabelled, so don't hand the wizard a 200-option list.
        option_set = (
            sorted(counter)
            if inferred in (InferredType.SELECT, InferredType.MULTI_SELECT)
            and 0 < len(counter) <= SELECT_MAX_DISTINCT
            else None
        )
        total_tokens = sum(counter.values())
        dominant_ratio = (counter.most_common(1)[0][1] / total_tokens) if total_tokens else 0.0
        # Spec 100: one ordered band per field, decided from Jira's own STABLE type
        # key (board rank, the dev-panel blob) or measured from the data (unused,
        # or a near-constant org-wide default). Never by literal field id or
        # English name — those two lists were what tied spec 90 to one instance.
        band, band_reason = band_of(
            meta.get("schema_key", ""),
            is_builtin,
            populated.get(fid, 0),
            sample_count,
            dominant_ratio,
        )
        results.append(
            InferredField(
                jira_id=fid,
                name=name,
                inferred_type=inferred,
                populated=populated.get(fid, 0),
                sample_count=sample_count,
                is_builtin=is_builtin,
                distinct_count=len(counter),
                dominant_ratio=dominant_ratio,
                schema_key=meta.get("schema_key", ""),
                band=band,
                band_reason=band_reason,
                native_target=schemakeys.native_target(meta.get("schema_key", ""), name),
                samples=samples.get(fid, []),
                distinct_values=option_set,
            )
        )
    # Order for the mapping grid: the fields that carry real data first, then the
    # machinery, then the empties, then the natively-handled columns. Within a
    # band, the more-populated and more-varied rise.
    results.sort(
        key=lambda f: (
            FIELD_BAND_ORDER[f.band],
            -f.populated,
            -f.distinct_count,
            f.name.lower(),
        )
    )
    return results
