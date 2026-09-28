"""The item dialect's builtin surface, as prose — DERIVED from the catalog.

An agent reads the MCP `search_items` parameter description and writes SLQ
from it. RADD-1428: that text was a hand-written list that had lost `type`,
`points`, `visibility`, `epic`/`epic.*`, `parent.*`, `past_cycle`,
`cycle.status` and the relative dates, so it described a smaller language than
the compiler accepts. Built from `SlqField` and `BUILTIN_OPS`, it cannot drift
again: a field added to the catalog appears here in the same change.
"""

from collections import defaultdict

from ..filters import NONE_LITERAL
from .catalog import BUILTIN_OPS, ME_LITERAL, FieldOps, SlqField
from .helpers import TODAY_LITERAL
from .lexer import CompareOp

#: The relative-date spellings `helpers.RELATIVE_DATE_RE` accepts, as examples.
RELATIVE_DATE_EXAMPLES = (TODAY_LITERAL, f"{TODAY_LITERAL}+3d", f"{TODAY_LITERAL}-2w")
#: How each part of an operator surface reads in the doc.
MEMBERSHIP_TEXT = "IN (a, b) / NOT IN"
EMPTY_TEXT = "IS [NOT] EMPTY"
SORT_ONLY_TEXT = "ORDER BY only"
#: Separates the lead-in from the groups, and one group from the next.
LEAD_IN = "Builtin fields by operator surface — "
GROUP_SEPARATOR = "; "
SORTABLE_LEAD_IN = "ORDER BY accepts: "


def surface_label(ops: FieldOps) -> str:
    """One field's operator surface as it reads in the doc — the compare ops
    in lexer order, then membership, then emptiness."""
    parts: list[str] = []
    compare = [op.value for op in CompareOp if op in ops.compare]
    if compare:
        parts.append(" ".join(compare))
    if ops.membership:
        parts.append(MEMBERSHIP_TEXT)
    if ops.empty:
        parts.append(EMPTY_TEXT)
    return ", ".join(parts) if parts else SORT_ONLY_TEXT


def builtin_fields_doc() -> str:
    """Every builtin field grouped by the operators it takes, then the
    sortable set, then the value sentinels. Catalog order within a group."""
    by_surface: dict[str, list[str]] = defaultdict(list)
    for field in SlqField:
        by_surface[surface_label(BUILTIN_OPS[field])].append(field.value)
    groups = GROUP_SEPARATOR.join(
        f"{label}: {', '.join(names)}" for label, names in by_surface.items()
    )
    sortable = ", ".join(field.value for field in SlqField if BUILTIN_OPS[field].sortable)
    return (
        f"{LEAD_IN}{groups}. "
        f"{SORTABLE_LEAD_IN}{sortable}. "
        "Any custom field by its registry key (operators follow its type). "
        f"Values: `{ME_LITERAL}` = the calling user on people fields (assignee, reporter "
        f"and their epic./parent. forms); `{NONE_LITERAL}` = an unset relation; dates are "
        f"YYYY-MM-DD or relative ({', '.join(RELATIVE_DATE_EXAMPLES)}); quote values with "
        "spaces ('In Progress')."
    )
