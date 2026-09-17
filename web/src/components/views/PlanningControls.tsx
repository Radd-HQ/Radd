import { Button } from "../Button";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";
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
  return <div className="border-b border-subtle bg-surface px-4 py-3" aria-label="Planning controls">
    <div className="flex flex-wrap items-end gap-4">
      <label className="flex items-center gap-2 pb-1 text-xs text-fg">
        <input type="checkbox" className="accent-accent" checked={options.showCompleted}
          onChange={e => onChange({ showCompleted: e.target.checked })} />
        Show completed issues in active sprints
      </label>
      <SelectField label="Backlog order" value={options.backlogOrder}
        onChange={e => onChange({backlogOrder: e.target.value as PlanningOptions["backlogOrder"]})}>
        <option value="priority">Priority</option><option value="recent">Recently updated</option><option value="manual">Manual</option>
      </SelectField>
      <TextField label="Search backlog" type="search" value={options.search} placeholder="Find an unscheduled issue…"
        onChange={e => onChange({search: e.target.value})} />
      {canEdit && <SelectField label="Hide a sprint for this view" value="" disabled={saving}
        onChange={e => { if(e.target.value) onHide(e.target.value); }}>
        <option value="">Choose a sprint…</option>
        {plan.scheduled.filter(g => !hidden.has(g.key)).map(g => <option key={g.key} value={g.key}>{g.label}</option>)}
      </SelectField>}
      {plan.hiddenCount > 0 && <Button variant="secondary" size="sm" disabled={!canEdit || saving} onClick={onRestore}
        title={canEdit ? "Restore sprints for everyone using this view" : "A view editor can restore hidden sprints"}>
        Restore {plan.hiddenCount} hidden {plan.hiddenCount === 1 ? "sprint" : "sprints"}
      </Button>}
      <Button variant="secondary" size="sm" aria-pressed={options.history}
        onClick={() => onChange({history: !options.history})}>Completed sprint history</Button>
      {options.history && <SelectField label="Historical sprint" value={plan.historyId ?? ""}
        onChange={e => onChange({historyCycle: e.target.value})}>
        {plan.historyCycles.length === 0 && <option value="">No completed sprints</option>}
        {plan.historyCycles.map(g => <option key={g.key} value={g.key}>{g.label}</option>)}
      </SelectField>}
    </div>
    <p className="mt-2 text-xs text-fg-muted">Active sprints first, then upcoming sprints and drafts. Sprint issues use manual order. Collapsing is personal; hiding changes the shared view.</p>
    {filtered && <p className="mt-1 text-xs text-fg-muted" role="status">Saved and temporary filters still apply to every section, including completed issues. Adjust the query above if expected work is missing.</p>}
  </div>;
}
