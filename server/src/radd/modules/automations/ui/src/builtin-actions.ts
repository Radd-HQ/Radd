/** Which node types this package edits itself, and when one of its built-in actions is complete
 * enough to save. Everything else is a plugin's: its own inspector, or its served schema, and the
 * server's validation — never a rule of ours. */
import {
  ActionType,
  VERDICT_BLOCK_TYPE,
  VERDICT_WARN_TYPE,
  type ActionParamValue,
  type RuleAction,
} from "./types";

/** The node-key prefix of the built-in actions — and, for the stored graphs that predate the move
 * (RADD-1387), of `action.send_email` and `action.add_participant`, which plugins now own. */
export const ACTION_TYPE_PREFIX = "action.";

/** This package's own actions, as node keys: exactly `ActionType`, nothing matched by prefix. */
const BUILTIN_ACTION_TYPES: ReadonlySet<string> = new Set(
  Object.values(ActionType).map((action) => `${ACTION_TYPE_PREFIX}${action}`),
);

/** Node types whose form lives here besides the built-in actions: the trigger, the SLQ filter and
 * source, the named gates and the verdict nodes. */
const CORE_EDITED_TYPES: ReadonlySet<string> = new Set([
  "trigger.event",
  "filter.slq",
  "search.slq",
  "gate.payload",
  "gate.project",
  "gate.field_changed",
  "gate.changed_by",
  "gate.state_category",
  "gate.comment",
  "gate.page_space",
  VERDICT_BLOCK_TYPE,
  VERDICT_WARN_TYPE,
]);

export function isBuiltinAction(type: string): boolean {
  return BUILTIN_ACTION_TYPES.has(type);
}

/** Whether this package draws the node's form. False = the contributing plugin's
 * `automation.node.inspector`, else a form from its served `params_schema`. */
export function hasCoreEditor(type: string): boolean {
  return CORE_EDITED_TYPES.has(type) || BUILTIN_ACTION_TYPES.has(type);
}

/** A non-empty string param, trimmed. */
const filled = (value: unknown): boolean => typeof value === "string" && value.trim() !== "";

/** RADD-1104: the built-in action nodes whose params the server would 422, so the editor refuses
 * up front. A plugin's action is never listed — its validity is the server's to decide. */
export function incompleteActionNodeIds(
  nodes: readonly { id: string; type: string; params: Record<string, unknown> }[],
): string[] {
  return nodes
    .filter(
      (node) =>
        isBuiltinAction(node.type) &&
        !isActionValid({
          type: node.type.slice(ACTION_TYPE_PREFIX.length),
          params: node.params as Record<string, ActionParamValue>,
        } as RuleAction),
    )
    .map((node) => node.id);
}

/** True when a built-in action's params are complete enough to save (spec 20 contract). */
function isActionValid(action: RuleAction): boolean {
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
  }
}
