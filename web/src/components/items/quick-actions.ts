import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { apiAutomationPath } from "../../lib/constants";
import { useCurrentUser } from "../../lib/hooks";
import { useUpdateItem } from "../../lib/item-mutations";
import { PRIORITY_META, PRIORITY_ORDER } from "../../lib/meta";
import {
  labelsQuery,
  runnableAutomationsQuery,
  statesQuery,
  usersQuery,
} from "../../lib/queries";
import type { Item, ItemUpdate } from "../../lib/types";

/** One entry in the editor's `/` quick-action menu. Filtered by every typed token
 * against label+keywords; `run` acts on the issue (never on the text). */
export interface QuickAction {
  id: string;
  label: string;
  /** Muted right-side detail in the menu. */
  hint?: string;
  /** Extra search text (not displayed). */
  keywords?: string;
  run: () => void | Promise<void>;
}

/**
 * The `/` menu for editors that have an ISSUE in context (description, comments):
 * built-in actions (assign / state / priority / labels) patch the item through the
 * normal mutation path, and every enabled MANUAL automation appears as a custom
 * action — the extensibility seam: rules created in settings, by extensions, or via
 * MCP all become slash actions with zero editor changes.
 */
export function useIssueQuickActions(item: Item, projectId: string): QuickAction[] {
  const me = useCurrentUser();
  const users = useQuery(usersQuery);
  const states = useQuery(statesQuery(projectId));
  const labels = useQuery(labelsQuery());
  const automations = useQuery(runnableAutomationsQuery());
  const updateItem = useUpdateItem();
  const queryClient = useQueryClient();

  const { mutate } = updateItem;
  return useMemo(() => {
    const patch = (body: ItemUpdate) => mutate({ itemId: item.id, patch: body });
    const actions: QuickAction[] = [];

    if (me) {
      actions.push({
        id: "assign-me",
        label: "Assign to me",
        hint: "assignee",
        run: () => patch({ assignee_id: me.id }),
      });
    }
    if (item.assignee) {
      actions.push({
        id: "unassign",
        label: "Unassign",
        hint: "assignee",
        run: () => patch({ assignee_id: null }),
      });
    }
    for (const user of users.data ?? []) {
      if (user.active === false) continue;
      actions.push({
        id: `assign-${user.id}`,
        label: `Assign: ${user.name}`,
        // No email to search on (RADD-769) — the member-floor directory does not
        // carry one. `/assign <name>` still matches, which is what people type.
        keywords: "assignee",
        run: () => patch({ assignee_id: user.id }),
      });
    }
    for (const state of states.data ?? []) {
      actions.push({
        id: `state-${state.id}`,
        label: `State: ${state.name}`,
        keywords: "move transition status",
        run: () => patch({ state_id: state.id }),
      });
    }
    for (const priority of PRIORITY_ORDER) {
      actions.push({
        id: `priority-${priority}`,
        label: `Priority: ${PRIORITY_META[priority].label}`,
        keywords: "priority set",
        run: () => patch({ priority }),
      });
    }
    for (const label of labels.data ?? []) {
      const has = item.labels.includes(label.name);
      actions.push({
        id: `label-${label.id}`,
        label: has ? `Remove label: ${label.name}` : `Add label: ${label.name}`,
        keywords: "tag label",
        run: () =>
          patch({
            labels: has
              ? item.labels.filter((name) => name !== label.name)
              : [...item.labels, label.name],
          }),
      });
    }
    for (const rule of automations.data ?? []) {
      actions.push({
        id: `automation-${rule.id}`,
        label: rule.name,
        hint: "automation",
        keywords: "run automation custom action",
        run: async () => {
          await api.post(`${apiAutomationPath(rule.id)}/run`, { item_id: item.id });
          // The rule ran as the system actor server-side — refetch everything visible.
          await queryClient.invalidateQueries();
        },
      });
    }
    return actions;
  }, [
    me,
    users.data,
    states.data,
    labels.data,
    automations.data,
    item.id,
    item.assignee,
    item.labels,
    mutate,
    queryClient,
  ]);
}
