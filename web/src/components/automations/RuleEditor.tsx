import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, apiAutomationPath } from "../../lib/constants";
import { SlqProbeStatus, useSlqValidation } from "../../lib/hooks";
import { automationCatalogQuery, queryKeys } from "../../lib/queries";
import { slqErrorOf } from "../../lib/slq";
import {
  MANUAL_TRIGGER,
  SCHEDULE_TRIGGER,
  type ConditionGroup,
  type Rule,
  type RuleCreate,
  type RuleSchedule,
  type RuleUpdate,
} from "../../lib/types";
import { Button } from "../Button";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";
import { SlqCheatSheet } from "../views/SlqCheatSheet";
import { SlqEditor } from "../views/SlqEditor";
import { ActionsBuilder, isActionValid } from "./ActionsBuilder";
import { ConditionsBuilder, isConditionValid } from "./ConditionsBuilder";
import { RuleTestPanel } from "./RuleTestPanel";
import { ScheduleEditor, defaultSchedule, isScheduleValid } from "./ScheduleEditor";

interface RuleEditorProps {
  /** The rule to edit, or null to create a new one. */
  rule: Rule | null;
  onDone: () => void;
}

/**
 * The automation rule builder (specs 20+58): name, a trigger picked from the
 * server's event catalog (any entity's change events, grouped), structured
 * EVENT conditions (who acted / what changed / old–new values), an SLQ
 * condition on the target item, and the ordered actions builder. Saves via
 * POST/PATCH; once persisted, "Test on an item" runs the `/test` dry-run.
 */
export function RuleEditor({ rule, onDone }: RuleEditorProps) {
  const queryClient = useQueryClient();
  const catalog = useQuery(automationCatalogQuery);
  const [persistedId, setPersistedId] = useState<string | null>(rule?.id ?? null);
  const [name, setName] = useState(rule?.name ?? "");
  const [trigger, setTrigger] = useState<string>(rule?.trigger ?? "item.created");
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  const [eventConditions, setEventConditions] = useState<ConditionGroup | null>(
    rule?.event_conditions ?? null,
  );
  const [condition, setCondition] = useState(rule?.condition_slq ?? "");
  const [actions, setActions] = useState(rule?.actions ?? []);
  const [schedule, setSchedule] = useState<RuleSchedule>(
    rule?.schedule ?? defaultSchedule("interval"),
  );

  const scheduled = trigger === SCHEDULE_TRIGGER;
  const triggerInfo = catalog.data?.triggers.find((t) => t.event_type === trigger);
  const groups = useMemo(() => {
    const grouped = new Map<string, { event_type: string; label: string }[]>();
    for (const t of catalog.data?.triggers ?? []) {
      grouped.set(t.group, [...(grouped.get(t.group) ?? []), t]);
    }
    return [...grouped.entries()];
  }, [catalog.data]);

  const probe = useSlqValidation(null, condition);
  const actionsValid = actions.length > 0 && actions.every(isActionValid);
  const conditionsValid =
    eventConditions === null ||
    (catalog.data !== undefined && isConditionValid(eventConditions, catalog.data));
  const canSave =
    name.trim() !== "" &&
    actionsValid &&
    conditionsValid &&
    (!scheduled || isScheduleValid(schedule)) &&
    probe.status !== SlqProbeStatus.invalid;

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: name.trim(),
        trigger,
        enabled,
        // Sentinel triggers carry no event conditions (manual: no event to
        // condition on; schedule: the server rejects them — spec 69).
        event_conditions: trigger === MANUAL_TRIGGER || scheduled ? null : eventConditions,
        condition_slq: condition,
        actions,
        schedule: scheduled ? schedule : null,
      };
      return persistedId
        ? api.patch<Rule>(apiAutomationPath(persistedId), payload satisfies RuleUpdate)
        : api.post<Rule>(ApiPath.automations, payload satisfies RuleCreate);
    },
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.automations });
      setPersistedId(saved.id);
    },
  });

  const saveSlqError = save.isError ? slqErrorOf(save.error) : null;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (canSave) save.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={onDone}
          className="inline-flex items-center gap-1.5 text-xs text-fg-secondary hover:text-heading cursor-pointer"
        >
          <ArrowLeft size={13} aria-hidden />
          Back to rules
        </button>
        {save.isSuccess && !save.isPending && (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
            <Check size={13} aria-hidden />
            Saved
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <TextField
          label="Rule name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Auto-triage blockers"
          maxLength={200}
          required
        />
        <SelectField
          label="Trigger"
          value={trigger}
          onChange={(event) => setTrigger(event.target.value)}
          hint={
            trigger === MANUAL_TRIGGER
              ? "Runs on demand from the editor's / menu"
              : scheduled
                ? "Runs item actions for every item matching the SLQ filter, max 200"
                : triggerInfo && !triggerInfo.item_scoped
                  ? "No target item on this event — item actions skip; create item / webhook / chat / notify still run"
                  : "The event that runs this rule"
          }
        >
          {groups.map(([group, triggers]) => (
            <optgroup key={group} label={group}>
              {triggers.map((t) => (
                <option key={t.event_type} value={t.event_type}>
                  {t.label}
                </option>
              ))}
            </optgroup>
          ))}
          <optgroup label="Scheduled">
            <option value={SCHEDULE_TRIGGER}>On a schedule</option>
          </optgroup>
          <optgroup label="On demand">
            <option value={MANUAL_TRIGGER}>Manual (editor / menu)</option>
          </optgroup>
        </SelectField>
      </div>

      <label className="flex w-fit cursor-pointer items-center gap-2 text-[13px] text-fg">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
          className="size-4 accent-accent"
        />
        Enabled
      </label>

      {scheduled && <ScheduleEditor value={schedule} onChange={setSchedule} />}

      {trigger !== MANUAL_TRIGGER && !scheduled && catalog.data && (
        <ConditionsBuilder
          catalog={catalog.data}
          trigger={triggerInfo}
          value={eventConditions}
          onChange={setEventConditions}
        />
      )}

      <div className="flex flex-col gap-2">
        <SlqEditor
          label={
            scheduled
              ? "Item filter (SLQ) — each run applies item actions to every match; empty runs universal actions only"
              : "Item condition (SLQ) — empty matches every item"
          }
          value={condition}
          onChange={setCondition}
          probe={probe}
          suggestScope={{}}
          placeholder={
            scheduled
              ? "target <= today+3d AND category != done"
              : "priority = blocker AND state != Done"
          }
        />
        <SlqCheatSheet fields={[]} projectId={null} />
      </div>

      <ActionsBuilder value={actions} onChange={setActions} />

      {save.isError && !saveSlqError && (
        <p className="text-xs text-red-400">{errorMessage(save.error)}</p>
      )}
      {saveSlqError && (
        <p className="text-xs text-red-400">Condition rejected on save: {saveSlqError.message}</p>
      )}

      <div className="flex items-center gap-2">
        <Button type="submit" disabled={!canSave || save.isPending}>
          {save.isPending ? "Saving…" : persistedId ? "Save changes" : "Create rule"}
        </Button>
        {!actionsValid && (
          <span className="text-xs text-fg-faint">Add at least one complete action to save.</span>
        )}
        {actionsValid && !conditionsValid && (
          <span className="text-xs text-fg-faint">Complete the event conditions to save.</span>
        )}
      </div>

      {persistedId ? (
        <RuleTestPanel ruleId={persistedId} />
      ) : (
        <p className="rounded-md border border-dashed border-subtle px-3 py-3 text-xs text-fg-faint">
          Save the rule to dry-run it against an item.
        </p>
      )}
    </form>
  );
}
