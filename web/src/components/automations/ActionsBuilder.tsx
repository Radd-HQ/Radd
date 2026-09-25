import { useQuery } from "@tanstack/react-query";
import { usePermissions } from "../../lib/hooks";
import {
  fieldsQuery,
  labelsQuery,
} from "../../lib/queries";
import {
  ActionType,
  Permission,
  type CustomFieldValue,
  type FieldDef,
  type RuleAction,
} from "../../lib/types";

/** Picker options gathered once for every action row (spec 20 actions builder). */
export interface PickerData {
  canChoosePeople: boolean;
  labelNames: string[];
  fields: FieldDef[];
}

const uniqueSorted = (values: string[]) => [...new Set(values)].sort((a, b) => a.localeCompare(b));

/** Remaining global registries; project-owned choices load in their controls. */
export function usePickerData(): PickerData {
  const perms = usePermissions();
  const labels = useQuery(labelsQuery());
  const fields = useQuery(fieldsQuery());
  return {
    canChoosePeople: perms.global(Permission.userManage),
    labelNames: uniqueSorted((labels.data ?? []).map((label) => label.name)),
    fields: fields.data ?? [],
  };
}


/** A non-empty string param, trimmed. */
const filled = (value: CustomFieldValue): boolean =>
  typeof value === "string" && value.trim() !== "";

/** RADD-1104: the graph's action nodes carry the same params under an
 * "action."-prefixed type — the validity contract is one function, applied to
 * both shapes, so the editor refuses up front what the server would 422. */
export function incompleteActionNodeIds(
  nodes: readonly { id: string; type: string; params: Record<string, unknown> }[],
): string[] {
  return nodes
    .filter(
      (node) =>
        node.type.startsWith("action.") &&
        !isActionValid({
          type: node.type.slice("action.".length),
          params: node.params,
        } as RuleAction),
    )
    .map((node) => node.id);
}

/** True when an action's params are complete enough to save (spec 20 contract). */
export function isActionValid(action: RuleAction): boolean {
  const p = action.params;
  switch (action.type) {
    case ActionType.setState:
      return filled(p.state);
    case ActionType.setPriority:
      return filled(p.priority);
    case ActionType.setAssignee:
      return filled(p.assignee);
    case ActionType.assignRoundRobin:
      return filled(p.team);
    case ActionType.setTeam:
      return filled(p.team);
    case ActionType.addLabel:
    case ActionType.removeLabel:
      return filled(p.label);
    case ActionType.setCycle:
      return filled(p.cycle);
    case ActionType.setRelease:
      return filled(p.release);
    case ActionType.setCustomField:
      return filled(p.key);
    case ActionType.addComment:
      return filled(p.body);
    case ActionType.setParent:
      return filled(p.parent);
    case ActionType.setType:
      return filled(p.type);
    case ActionType.setReporter:
      return filled(p.reporter);
    case ActionType.setDates:
      return filled(p.start) || filled(p.target);
    case ActionType.setEstimate:
      return filled(p.points);
    case ActionType.setFlag:
    case ActionType.archiveItem:
      return true;
    case ActionType.setVisibility:
      return filled(p.visibility);
    case ActionType.linkItem:
      return filled(p.target) && filled(p.link_type);
    case ActionType.addWatcher:
    case ActionType.addParticipant:
      return filled(p.user);
    case ActionType.moveToProject:
      return filled(p.project);
    case ActionType.createItem:
      return filled(p.project) && filled(p.title);
    case ActionType.sendWebhook:
      return filled(p.url);
    case ActionType.postChat:
      return filled(p.webhook_url) && filled(p.message);
    case ActionType.notifyUser:
      return filled(p.user) && filled(p.message);
    case ActionType.sendEmail:
      return filled(p.to) && filled(p.subject) && filled(p.body);
    default:
      return false;
  }
}
