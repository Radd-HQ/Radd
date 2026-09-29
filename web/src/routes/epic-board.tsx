import { useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { EmptyState } from "@radd/plugin-sdk";
import { Spinner } from "../components/Spinner";
import { itemByKeyQuery } from "../lib/queries";
import { ItemKind, ViewAxis, ViewType, type Item, type View } from "../lib/types";
import { ViewPage } from "./view";

/** The synthetic view's id prefix — what keys its per-view display state. */
const EPIC_BOARD_ID_PREFIX = "epic:";

/**
 * RADD-1493: an epic as an ALL-PROJECTS board. Spec 80 said "views are the
 * cross-project surface" and left building one to the person; this is that view,
 * built from the epic on the spot — no saved row, nothing to delete, never
 * editable. Columns are the state CATEGORIES (the vocabulary every project
 * shares; state names do not cross projects) and the lanes are the projects the
 * work lives in, so the whole picture is one screen.
 */
export function epicBoardView(epic: Item): View {
  const query = `epic = ${epic.key} AND kind != epic`;
  return {
    id: `${EPIC_BOARD_ID_PREFIX}${epic.key}`,
    project_id: null,
    name: `${epic.key} · ${epic.title}`,
    view_type: ViewType.board,
    query,
    group_by: ViewAxis.stateCategory,
    swimlane_by: ViewAxis.project,
    cycle_filter: null,
    quick_filters: [],
    wip_limits: null,
    columns: null,
    card_layout: null,
    column_order: null,
    swimlane_order: null,
    collapse_empty_columns: false,
    hidden_columns: null,
    owner_id: null,
    owner: null,
    global_access: null,
    shares: [],
    shared: true,
    can_edit: false,
    can_manage: false,
    position: 0,
    query_string: new URLSearchParams({ q: query }).toString(),
    created_at: epic.created_at,
    updated_at: epic.updated_at,
  };
}

export function EpicBoardPage() {
  const { itemKey = "" } = useParams({ strict: false });
  const epic = useQuery(itemByKeyQuery(itemKey));
  if (epic.isPending) return <Spinner label="Loading epic…" />;
  if (epic.isError || epic.data.kind !== ItemKind.epic) {
    return <EmptyState message={`${itemKey} is not an epic you can open as a board.`}>Not an epic</EmptyState>;
  }
  return <ViewPage synthetic={epicBoardView(epic.data)} />;
}
