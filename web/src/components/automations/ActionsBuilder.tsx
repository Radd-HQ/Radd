import { useId } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
import { ACTION_TYPE_LABELS, ACTION_TYPE_ORDER } from "../../lib/meta";
import {
  cyclesQuery,
  fieldsQuery,
  labelsQuery,
  projectsQuery,
  releasesQuery,
  statesQuery,
  teamsQuery,
  usersAdminQuery,
} from "../../lib/queries";
import {
  ActionType,
  CommentVisibility,
  Priority,
  type ActionTypeValue,
  type CustomFieldValue,
  type FieldDef,
  type RuleAction,
} from "../../lib/types";
import { useKeyedRows } from "../../lib/keyed-rows";
import { Button } from "../Button";
import { SelectField } from "../SelectField";
import { ActionParams } from "./ActionParams";
import { IconButton } from "../IconButton";

/** Picker options gathered once for every action row (spec 20 actions builder). */
export interface PickerData {
  userEmails: { email: string; name: string }[];
  teamNames: string[];
  labelNames: string[];
  cycleNames: string[];
  stateNames: string[];
  releaseVersions: string[];
  projectKeys: string[];
  fields: FieldDef[];
}

const uniqueSorted = (values: string[]) => [...new Set(values)].sort((a, b) => a.localeCompare(b));

/** Fetch the global pickers plus per-project state/release names. */
export function usePickerData(): PickerData {
  // The ADMIN directory (RADD-769): an automation stores its assignee by
  // EMAIL, so this picker needs the address as a VALUE, not as decoration —
  // which is the half of the directory that stays behind `user.manage`.
  const users = useQuery(usersAdminQuery({}));
  const teams = useQuery(teamsQuery());
  const labels = useQuery(labelsQuery());
  const cycles = useQuery(cyclesQuery());
  const fields = useQuery(fieldsQuery());
  const projects = useQuery(projectsQuery());
  const projectIds = (projects.data ?? []).map((project) => project.id);
  const states = useQueries({ queries: projectIds.map((id) => statesQuery(id)) });
  const releases = useQueries({ queries: projectIds.map((id) => releasesQuery(id)) });
  return {
    userEmails: (users.data ?? [])
      .filter((user) => user.active)
      .map((user) => ({ email: user.email, name: user.name })),
    teamNames: (teams.data ?? []).map((team) => team.name),
    labelNames: uniqueSorted((labels.data ?? []).map((label) => label.name)),
    cycleNames: (cycles.data ?? []).map((cycle) => cycle.name),
    stateNames: uniqueSorted(states.flatMap((query) => (query.data ?? []).map((state) => state.name))),
    releaseVersions: uniqueSorted(
      releases.flatMap((query) => (query.data ?? []).map((release) => release.version)),
    ),
    projectKeys: (projects.data ?? []).map((project) => project.key),
    fields: fields.data ?? [],
  };
}

/** Fresh params for a freshly-picked action type. */
function defaultParams(type: ActionTypeValue): Record<string, CustomFieldValue> {
  switch (type) {
    case ActionType.setState:
      return { state: "" };
    case ActionType.setPriority:
      return { priority: Priority.normal };
    case ActionType.setAssignee:
      return { assignee: "" };
    case ActionType.assignRoundRobin:
      return { team: "" };
    case ActionType.setTeam:
      return { team: "" };
    case ActionType.addLabel:
    case ActionType.removeLabel:
      return { label: "" };
    case ActionType.setCycle:
      return { cycle: "" };
    case ActionType.setRelease:
      return { release: "" };
    case ActionType.setCustomField:
      return { key: "", value: null };
    case ActionType.addComment:
      return { body: "", visibility: CommentVisibility.public };
    case ActionType.createItem:
      return { project: "", title: "", description: "" };
    case ActionType.sendWebhook:
      return { url: "", secret: "" };
    case ActionType.postChat:
      return { webhook_url: "", message: "" };
    case ActionType.notifyUser:
      return { user: "", message: "" };
    case ActionType.sendEmail:
      return { to: "", subject: "", body: "" };
  }
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

interface ActionsBuilderProps {
  value: RuleAction[];
  onChange: (actions: RuleAction[]) => void;
}

/** Ordered list of action rows — the "what a rule does" builder (spec 20). */
export function ActionsBuilder({ value, onChange }: ActionsBuilderProps) {
  const pickers = usePickerData();
  const listId = useId();

  // Stable per-row keys (RADD-901): rows are full of selects and param inputs,
  // and keying by index re-keyed everything below a removal.
  const rows = useKeyedRows(value, onChange);
  const update = (index: number, next: RuleAction) =>
    onChange(value.map((action, i) => (i === index ? next : action)));
  const move = (index: number, delta: number) => rows.swap(index, index + delta);
  const add = () =>
    rows.add({ type: ActionType.setState, params: defaultParams(ActionType.setState) });

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-fg-secondary">Actions</span>
        <span className="text-[11px] text-fg-faint">Applied in order to every matching item</span>
      </div>

      {/* Shared suggestion lists for the free-text name/version fields. */}
      <datalist id={`${listId}-states`}>
        {pickers.stateNames.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
      <datalist id={`${listId}-labels`}>
        {pickers.labelNames.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
      <datalist id={`${listId}-releases`}>
        {pickers.releaseVersions.map((version) => (
          <option key={version} value={version} />
        ))}
      </datalist>

      {value.length === 0 && (
        <p className="rounded-md border border-dashed border-subtle px-3 py-4 text-center text-xs text-fg-faint">
          No actions yet — a rule needs at least one.
        </p>
      )}

      <ul className="flex flex-col gap-2">
        {value.map((action, index) => (
          <li
            key={rows.keys[index]}
            className="flex items-start gap-2 rounded-md border border-subtle bg-surface/40 p-2.5"
          >
            <div className="flex flex-col gap-0.5 pt-5">
              <button
                type="button"
                onClick={() => move(index, -1)}
                disabled={index === 0}
                aria-label="Move action up"
                className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg disabled:opacity-30 cursor-pointer disabled:cursor-default"
              >
                <ChevronUp size={13} />
              </button>
              <button
                type="button"
                onClick={() => move(index, 1)}
                disabled={index === value.length - 1}
                aria-label="Move action down"
                className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg disabled:opacity-30 cursor-pointer disabled:cursor-default"
              >
                <ChevronDown size={13} />
              </button>
            </div>
            <div className="grid min-w-0 flex-1 grid-cols-2 gap-2.5">
              <SelectField
                label={`Action ${index + 1}`}
                value={action.type}
                onChange={(event) => {
                  const type = event.target.value as ActionTypeValue;
                  update(index, { type, params: defaultParams(type) });
                }}
              >
                {ACTION_TYPE_ORDER.map((type) => (
                  <option key={type} value={type}>
                    {ACTION_TYPE_LABELS[type]}
                  </option>
                ))}
              </SelectField>
              <ActionParams
                action={action}
                pickers={pickers}
                listId={listId}
                onParams={(params) => update(index, { ...action, params })}
              />
            </div>
            <IconButton
              danger
              onClick={() => rows.removeAt(index)}
              aria-label={`Remove action ${index + 1}`}
              className="mt-6"
            >
              <Trash2 size={14} />
            </IconButton>
          </li>
        ))}
      </ul>

      <Button variant="secondary" size="sm" className="w-fit" onClick={add}>
        <Plus size={13} aria-hidden />
        Add action
      </Button>
    </div>
  );
}
