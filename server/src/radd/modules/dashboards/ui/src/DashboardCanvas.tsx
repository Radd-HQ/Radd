import { useState, type ReactNode } from "react";
import { useBlocker } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { Button, ErrorText, useConfirm } from "@radd/plugin-sdk";
import type { Dashboard, DashboardWidget } from "./types";
import { WidgetGrid } from "./WidgetGrid";
import { WidgetModal } from "./WidgetModal";

/**
 * The widget canvas every dashboard draws on — a shared dashboard and My Work alike. Customize
 * opens a local draft (drag, resize, add, configure); Save commits it against the layout it
 * started from, so a concurrent edit is a conflict rather than a silent overwrite. `defaults`
 * (My Work only) offers Reset to default and makes a collapse save straight away.
 */
export function DashboardCanvas({ dashboard, save, defaults, render }: {
  dashboard: Dashboard; save: (widgets: DashboardWidget[], expected: DashboardWidget[]) => Promise<unknown>;
  defaults?: () => Promise<DashboardWidget[]>; render: (widget: DashboardWidget) => ReactNode;
}) {
  const [draft, setDraft] = useState<DashboardWidget[] | null>(null);
  const [expected, setExpected] = useState<DashboardWidget[]>([]);
  const [modal, setModal] = useState<{ widget?: DashboardWidget } | null>(null);
  const [localCollapsed, setLocalCollapsed] = useState<Record<string, boolean>>({});
  const [confirmDialog, confirm] = useConfirm();
  const editing = draft !== null;
  const dirty = editing && JSON.stringify(draft) !== JSON.stringify(expected);
  useBlocker({
    shouldBlockFn: async () => dirty && !(await confirm({ title: "Discard changes", message: "Discard unsaved dashboard changes?", confirmLabel: "Discard", danger: true })),
    enableBeforeUnload: dirty,
  });
  const mutation = useMutation({ mutationFn: ({ rows, original, finish }: { rows: DashboardWidget[]; original: DashboardWidget[]; finish: boolean }) => save(rows.map((w, position) => ({ ...w, position })), original).then(() => { if (finish) setDraft(null); }) });
  const reset = useMutation({ mutationFn: async () => { if (defaults) setDraft(await defaults()); } });
  const rows = (draft ?? dashboard.widgets).map(w => ({ ...w, collapsed: editing ? w.collapsed : localCollapsed[w.id] ?? w.collapsed }));
  return <div className="space-y-3">
    <div className="flex flex-wrap items-center justify-end gap-2">
      {editing ? <>
        <span className="mr-auto text-xs text-fg-muted">Drag a handle to move; drag an edge or corner to resize.</span>
        <Button disabled={mutation.isPending} onClick={() => setModal({})}>Add widget</Button>
        {defaults && <Button variant="ghost" disabled={reset.isPending || mutation.isPending} onClick={() => reset.mutate()}>Reset to default</Button>}
        <Button variant="ghost" disabled={mutation.isPending} onClick={() => { setDraft(null); setModal(null); }}>Cancel</Button>
        <Button disabled={mutation.isPending} onClick={() => mutation.mutate({ rows: draft, original: expected, finish: true })}>{mutation.isPending ? "Saving…" : "Save"}</Button>
      </> : dashboard.can_edit && <Button disabled={mutation.isPending} onClick={() => { setExpected(structuredClone(dashboard.widgets)); setDraft(structuredClone(rows)); setLocalCollapsed({}); }}>Customize</Button>}
    </div>
    {(mutation.isError || reset.isError) && <ErrorText error={mutation.error ?? reset.error} />}
    {!rows.length && <p className="p-6 text-sm text-fg-muted">No widgets. Choose Customize to add one.</p>}
    <div className={mutation.isPending ? "pointer-events-none opacity-70" : ""}>
      <WidgetGrid widgets={rows} editing={editing} onChange={setDraft} onConfigure={widget => setModal({ widget })}
        onCollapse={widget => {
          const next = rows.map(w => w.id === widget.id ? { ...w, collapsed: !w.collapsed } : w);
          if (editing) setDraft(next);
          else if (defaults) mutation.mutate({ rows: next, original: dashboard.widgets, finish: false });
          else setLocalCollapsed(old => ({ ...old, [widget.id]: !widget.collapsed }));
        }} render={render} />
    </div>
    {modal && editing && <WidgetModal dashboard={{ ...dashboard, widgets: draft }} personal={!!defaults} widget={modal.widget} onClose={() => setModal(null)}
      onDraft={widget => setDraft(rows.some(w => w.id === widget.id) ? rows.map(w => w.id === widget.id ? widget : w) : [...rows, widget])} />}
    {confirmDialog}
  </div>;
}
