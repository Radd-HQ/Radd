from enum import StrEnum


class FieldType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"  # ISO date string, YYYY-MM-DD
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    USER = "user"  # user identifier; validated against users when the auth module lands
    URL = "url"
    DURATION = "duration"  # whole minutes, >= 0


SELECT_TYPES = frozenset({FieldType.SELECT, FieldType.MULTI_SELECT})


class FieldDisplay(StrEnum):
    """How a field renders (spec 52) — a presentation hint, editable per field.
    Mainly for select/multi_select: `chips` (inline toggles) vs `dropdown`
    (a compact popover that avoids filling space when there are many options)."""

    CHIPS = "chips"
    DROPDOWN = "dropdown"


class FieldSource(StrEnum):
    USER = "user"
    CONNECTOR = "connector"  # written by extensions; read-only in the UI


class FieldSubject(StrEnum):
    """What a field-permission grant points at (spec 07)."""

    ROLE = "role"  # a row in auth `roles` (builtin or custom)
    TEAM = "team"  # a row in teams `teams`


class FieldAccess(StrEnum):
    READ = "read"
    WRITE = "write"


class FieldEvent(StrEnum):
    CREATED = "field.created"
    UPDATED = "field.updated"  # emitted on permission-grant replacement
    DELETED = "field.deleted"  # spec 87 — definition + its grants; item values are orphaned


class FieldEntity(StrEnum):
    FIELD = "field"


class BuiltinItemField(StrEnum):
    """Builtin work-item fields that can carry write rules (spec 36). Default is
    write-open to item.update holders; a rule restricts the field to its subjects."""

    TITLE = "title"
    DESCRIPTION = "description"
    STATE = "state"
    PRIORITY = "priority"
    ASSIGNEE = "assignee"
    REPORTER = "reporter"
    TEAM = "team"
    LABELS = "labels"
    PARENT = "parent"
    START_DATE = "start_date"
    TARGET_DATE = "target_date"
    CYCLE = "cycle"
    RELEASE = "release"
    FLAGGED = "flagged"
    ESTIMATE_POINTS = "estimate_points"


# Builtin fields that support a READ rule (spec 50). Title/state/priority are the
# structural identifiers of every list/board/search row — blanking them would break
# those surfaces (and can't be nulled in the read model), so they stay write-only.
READ_RESTRICTABLE_BUILTINS: frozenset["BuiltinItemField"] = frozenset(
    field
    for field in BuiltinItemField
    if field not in {BuiltinItemField.TITLE, BuiltinItemField.STATE, BuiltinItemField.PRIORITY}
)
