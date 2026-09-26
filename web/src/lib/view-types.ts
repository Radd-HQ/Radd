/**
 * Saved-view TYPES as the shell sees them (RADD-1396): the builtins, plus whatever the enabled
 * plugins contribute through `/capabilities`. The shell names no plugin type — a type's icon, its
 * list surface and its own sidebar section all arrive as data.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, GanttChartSquare, List, SquareKanban, type LucideIcon } from "lucide-react";
import { capabilitiesQuery } from "./queries";
import { iconFor } from "./icons";
import { ViewType, type ViewTypeOption } from "./types";

const BUILTIN_ICONS: Record<string, LucideIcon> = {
  [ViewType.board]: SquareKanban,
  [ViewType.list]: List,
  [ViewType.planning]: CalendarClock,
  [ViewType.roadmap]: GanttChartSquare,
};

/** Is `viewType` one of the host's own? */
export function isBuiltinViewType(viewType: string | undefined): boolean {
  return viewType !== undefined && (Object.values(ViewType) as string[]).includes(viewType);
}

/** Group-by / swimlane axes are a board's and a list's alone; every other type is flat or draws
 *  its own grouping (planning's cycles, the roadmap's timeline, a plugin's surface). */
export function viewTypeHasAxes(viewType: string | undefined): boolean {
  return viewType === ViewType.board || viewType === ViewType.list;
}

/** A view type's icon: a builtin's own, else the icon its plugin declared, else a list. */
export function viewTypeIcon(viewType: string, option?: ViewTypeOption): LucideIcon {
  return BUILTIN_ICONS[viewType] ?? iconFor(option?.icon) ?? List;
}

export interface ViewTypes {
  /** False until `/capabilities` answers — a plugin type cannot be told from a missing one yet. */
  loaded: boolean;
  byKey: ReadonlyMap<string, ViewTypeOption>;
  /** The types whose views are listed in a sidebar section of their own. */
  sectioned: readonly ViewTypeOption[];
}

/** The enabled plugins' view types, keyed; withdrawn live with their plugin. */
export function useViewTypes(): ViewTypes {
  const { data } = useQuery(capabilitiesQuery);
  return useMemo(() => {
    const options = data?.view_types ?? [];
    return {
      loaded: data !== undefined,
      byKey: new Map(options.map((option) => [option.key, option])),
      sectioned: options.filter((option) => Boolean(option.sidebar_section)),
    };
  }, [data]);
}
