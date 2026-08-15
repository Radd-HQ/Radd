"""Item service — the items module's use-case layer.

Split into per-concern modules that stack bottom-up with no cycles:

    visibility, queries          (leaves)
    relations → queries
    read      → queries, visibility
    listing   → visibility
    links     → queries, read, visibility
    core      → links, queries, read, relations, visibility

This barrel is the module's PUBLIC surface — the same 25 names the former
`service.py` exposed, so every `from radd.modules.items.service import …` site
keeps working unchanged. The ~30 `_`-prefixed helpers stay private to the
package (rule 1: other modules talk to items through these functions only).
An items-internal caller that genuinely needs one imports it from the concern
module directly, e.g. `from .service.visibility import _internal_visible`.
"""

from .core import (
    create_item,
    delete_item,
    move_open_cycle_items,
    reassign_state,
    reorder_item,
    set_archived,
    star_item,
    unstar_item,
    update_item,
)
from .customvalues import (
    count_with_value,
    drop_from_multi_select,
    migrate_custom_field_value,
)
from .links import add_item_link, link_search, remove_item_link, sync_mention_links
from .listing import list_items, validate_slq
from .queries import (
    EpicRef,
    count_items_assigned_to_team,
    count_items_in_state,
    epics_for_items,
    cycle_points_totals,
    cycle_state_category_counts,
    estimate_points_by_ids,
    find_item_by_key,
    item_ids_for_projects,
    items_by_ids,
    require_item,
    require_readable_item,
)
from .clone import clone_item
from .convert import convert_item_kind
from .read import get_item, get_item_by_key
from .refs import item_ref, ref_from
from .visibility import (
    denied_slq_fields,
    ensure_item_relation,
    projects_with_team_items,
    projects_with_user_items,
    relation_read_clause,
)

__all__ = [
    "add_item_link",
    "item_ref",
    "ref_from",
    "denied_slq_fields",
    "ensure_item_relation",
    "projects_with_team_items",
    "projects_with_user_items",
    "relation_read_clause",
    "count_items_assigned_to_team",
    "count_items_in_state",
    "count_with_value",
    "drop_from_multi_select",
    "migrate_custom_field_value",
    "reassign_state",
    "create_item",
    "cycle_points_totals",
    "cycle_state_category_counts",
    "delete_item",
    "EpicRef",
    "epics_for_items",
    "estimate_points_by_ids",
    "find_item_by_key",
    "get_item",
    "get_item_by_key",
    "item_ids_for_projects",
    "items_by_ids",
    "link_search",
    "list_items",
    "move_open_cycle_items",
    "remove_item_link",
    "reorder_item",
    "require_item",
    "require_readable_item",
    "set_archived",
    "star_item",
    "sync_mention_links",
    "unstar_item",
    "update_item",
    "validate_slq",
]
