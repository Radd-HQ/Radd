"""Field-mapping suggestion + validation — PURE. One decision per inbound field:
ignore, map into an existing field, create one, or route into a native concept."""

from __future__ import annotations

import re
from dataclasses import dataclass

from radd.modules.fields.types import SELECT_TYPES, FieldType

from . import schemakeys
from .schemas import FieldMappingEntry
from .types import BuiltinTarget, FieldAction, InferredField, InferredType

# InferredType → the Radd FieldType a "create" defaults to. UNKNOWN degrades to
# text (the lossless catch-all) rather than guessing a structured type.
_RADD_TYPE: dict[InferredType, FieldType] = {
    InferredType.TEXT: FieldType.TEXT,
    InferredType.SELECT: FieldType.SELECT,
    InferredType.MULTI_SELECT: FieldType.MULTI_SELECT,
    InferredType.NUMBER: FieldType.NUMBER,
    InferredType.DATE: FieldType.DATE,
    InferredType.USER: FieldType.USER,
    InferredType.UNKNOWN: FieldType.TEXT,
}

_KEY_MAX = 50


def radd_type_for(inferred: InferredType) -> FieldType:
    return _RADD_TYPE.get(inferred, FieldType.TEXT)


def slug(name: str) -> str:
    """A Jira field name → a valid Radd field key (^[a-z][a-z0-9_]{0,49}$).

    Non-alphanumerics collapse to underscores, a leading digit/underscore is
    prefixed so the pattern holds, and it is trimmed to length. Deterministic, so
    the same field name always proposes the same key."""
    lowered = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not lowered:
        lowered = "field"
    if not lowered[0].isalpha():
        lowered = f"f_{lowered}"
    return lowered[:_KEY_MAX]


# Jira custom fields whose NAME means a native Radd concept — suggested as a
# native-target mapping rather than a text custom field. The admin can override.
_NATIVE_BY_NAME: dict[str, BuiltinTarget] = {
    "epic link": BuiltinTarget.PARENT,
    "parent link": BuiltinTarget.PARENT,
    "watchers": BuiltinTarget.WATCHERS,
    "watcher": BuiltinTarget.WATCHERS,
    # Jira's own names for the same column, across Server/Cloud and the agile plugin.
    "story points": BuiltinTarget.POINTS,
    "story point estimate": BuiltinTarget.POINTS,
    "points": BuiltinTarget.POINTS,
}


def suggest_mappings(
    fields: list[InferredField], existing_keys: set[str]
) -> list[FieldMappingEntry]:
    """The grid the wizard opens with:

    - built-in Jira fields → `builtin` (handled natively, shown for context),
    - a native concept by type key, else by name → `native`,
    - anything outside the IN_USE band → `ignore`,
    - a slug that names an existing Radd field → `map` to it,
    - everything else → `create`, with the inferred type and the observed options.
    """
    suggestions: list[FieldMappingEntry] = []

    def entry(f: InferredField, action: FieldAction, **kw) -> FieldMappingEntry:
        return FieldMappingEntry(jira_id=f.jira_id, jira_name=f.name, action=action, **kw)

    for f in fields:
        if f.is_builtin:
            suggestions.append(entry(f, FieldAction.BUILTIN))
            continue
        native = schemakeys.native_target(f.schema_key, f.name) or _NATIVE_BY_NAME.get(
            f.name.strip().lower()
        )
        if native is not None:
            suggestions.append(entry(f, FieldAction.NATIVE, builtin_target=native))
            continue
        if f.ignored_by_default:  # UNUSED or NOISE — collapsed in the grid too
            suggestions.append(entry(f, FieldAction.IGNORE))
            continue
        key = slug(f.name)
        radd_type = radd_type_for(f.inferred_type)
        if key in existing_keys:
            suggestions.append(entry(f, FieldAction.MAP, target_key=key))
            continue
        suggestions.append(
            entry(
                f,
                FieldAction.CREATE,
                target_key=key,
                create_type=radd_type,
                create_name=f.name[:200],
                create_options=(list(f.distinct_values) if radd_type in SELECT_TYPES and f.distinct_values else None),
            )
        )
    return suggestions


# --- validation (given the live catalog) --------------------------------------


@dataclass(frozen=True)
class MappingProblem:
    jira_id: str
    message: str


def validate_mappings(
    mappings: list[FieldMappingEntry],
    existing: dict[str, FieldType],
) -> list[MappingProblem]:
    """Check a mapping set against the live custom-field catalog (`existing`:
    key → its Radd type). Returns problems; empty = ready to run. A missing target
    key or native target cannot reach here: `FieldMappingEntry` refuses both.

    Two `create`s claiming the same key would collide — caught here rather than
    mid-import."""
    problems: list[MappingProblem] = []
    claimed_new: dict[str, str] = {}  # new key → the jira_id that first claimed it
    for m in mappings:
        if m.action in (FieldAction.IGNORE, FieldAction.BUILTIN, FieldAction.NATIVE):
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", m.target_key):
            problems.append(
                MappingProblem(m.jira_id, f"'{m.target_key}' is not a valid field key")
            )
            continue
        if m.action is FieldAction.MAP:
            # Only existence is enforced. Value/type compatibility is the
            # importer's job (`clean_custom_fields` drops values a field won't
            # take), so mapping a Jira select into a Radd text field is allowed —
            # text accepts anything, and blocking it would be needless friction.
            if m.target_key not in existing:
                problems.append(
                    MappingProblem(m.jira_id, f"no custom field '{m.target_key}' exists to map into")
                )
        elif m.action is FieldAction.CREATE:
            if m.target_key in existing:
                problems.append(
                    MappingProblem(
                        m.jira_id,
                        f"'{m.target_key}' already exists — map to it instead of creating",
                    )
                )
            if m.create_type is None:
                problems.append(MappingProblem(m.jira_id, "a field type is required to create"))
            elif m.create_type in SELECT_TYPES and not m.create_options:
                problems.append(
                    MappingProblem(m.jira_id, f"{m.create_type} needs a non-empty option set")
                )
            if m.target_key in claimed_new:
                problems.append(
                    MappingProblem(
                        m.jira_id,
                        f"'{m.target_key}' is created by more than one field — keys must be unique",
                    )
                )
            claimed_new[m.target_key] = m.jira_id
    return problems
