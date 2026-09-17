import { Button } from "../Button";
import { SelectField } from "../SelectField";
import type { PlanningOptions, planningQueries } from "../../lib/planning-query";

export function PlanningControls({ options, onChange, plan, hidden, canEdit, saving, onHide, onRestore, filtered }: {
  options: PlanningOptions;
  onChange: (patch: Partial<PlanningOptions>) => void;
  plan: ReturnType<typeof planningQueries>;
  hidden: Set<string>;
  canEdit: boolean;
  saving: boolean;
  onHide: (id: string) => void;
  onRestore: () => void;
  filtered: boolean;
}) {
  return <div className="space-y-3" aria-label="Planning display options">
    <p className="text-xs font-semibold text-fg">Planning</p>
    <label className="flex items-center gap-2 text-xs text-fg">
      <input type="checkbox" className="accent-accent" checked={options.showCompleted}
        onChange={e => onChange({ showCompleted: e.target.checked })} />
      Show completed issues in active sprints
    </label>
    <label className="flex items-center gap-2 text-xs text-fg">
      <input type="checkbox" className="accent-accent" checked={options.history}
        onChange={e => onChange({history: e.target.checked})} />
      Completed sprint history
    </label>
    {options.history && <SelectField label="Historical sprint" value={plan.historyId ?? ""}
      onChange={e => onChange({historyCycle: e.target.value})}>
      {plan.historyCycles.length === 0 && <option value="">No completed sprints</option>}
      {plan.historyCycles.map(g => <option key={g.key} value={g.key}>{g.label}</option>)}
    </SelectField>}
    {canEdit && <SelectField label="Hide a sprint for this view" value="" disabled={saving}
      onChange={e => { if(e.target.value) onHide(e.target.value); }}>
      <option value="">Choose a sprint…</option>
      {plan.scheduled.filter(g => !hidden.has(g.key)).map(g => <option key={g.key} value={g.key}>{g.label}</option>)}
    </SelectField>}
    {plan.hiddenCount > 0 && <Button variant="secondary" size="sm" disabled={!canEdit || saving} onClick={onRestore}
      title={canEdit ? "Restore sprints for everyone using this view" : "A view editor can restore hidden sprints"}>
      Restore {plan.hiddenCount} hidden {plan.hiddenCount === 1 ? "sprint" : "sprints"}
    </Button>}
    <p className="text-xs text-fg-muted">Collapsing is personal. Hiding changes the shared view.</p>
    {filtered && <p className="text-xs text-fg-muted">Saved and temporary filters still apply, including to completed issues.</p>}
  </div>;
}
