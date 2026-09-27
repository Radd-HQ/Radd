import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  api, Button, ErrorText, invalidateEntities, Modal, positionedErrorOf, SelectField, SlotId, TextField,
  useCapabilities, useDisabledMatches, useSlotMatch, type DashboardWidgetConfigProps,
} from "@radd/plugin-sdk";
import { dashboardWidgetPath, dashboardWidgetsPath } from "./queries";
import {
  WidgetType, type Dashboard, type DashboardWidget, type DashboardWidgetCreate, type DashboardWidgetUpdate, type WidgetConfig,
} from "./types";
import { configOf, draftOf, isComplete, WidgetConfigFields } from "./WidgetConfigFields";
import { isOwnType, PERSONAL_OPTIONS, SLQ_TYPES, WIDGET_TYPE_OPTIONS, WIDTH_OPTIONS } from "./widget-meta";

/**
 * Add/Edit widget dialog (spec 75): a type picker and that type's config form. On My Work
 * (`personal`) the picker also offers My Work's own kinds and every PERSONAL type a plugin
 * contributes; a shared dashboard offers neither. A plugin's type brings its own settings form
 * through `dashboard.widget.config` (RADD-1462) and owns its config whole; one without a form
 * takes none. The server re-validates shape and references on save (422/409). With `onDraft` the
 * widget lands in the canvas's draft instead of saving.
 */
export function WidgetModal({ dashboard, widget, onClose, onDraft, personal = false }: {
  dashboard: Dashboard;
  personal?: boolean;
  onDraft?: (widget: DashboardWidget) => void;
  /** When set, edit this widget's config in place (type is immutable). */
  widget?: DashboardWidget;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [type, setType] = useState<string>(widget?.widget_type ?? WidgetType.slqCount);
  const [title, setTitle] = useState(widget?.title ?? "");
  const [width, setWidth] = useState(String(widget?.width ?? 4));
  const [draft, setDraft] = useState(() => draftOf(widget?.config));
  const [slqValid, setSlqValid] = useState(true);
  // A plugin type's config, whole — its form replaces it on every change and may veto the save.
  const [pluginConfig, setPluginConfig] = useState<Record<string, unknown>>(() => ({ ...(widget?.config ?? {}) }));
  const [pluginValid, setPluginValid] = useState(true);
  const pluginForm = useSlotMatch(SlotId.dashboardWidgetConfig, type);

  // Contributed types (spec 94) join the picker — a turned-off contribution drops out (spec 94).
  const disabled = useDisabledMatches(SlotId.dashboardWidget);
  const contributed = (useCapabilities()?.widget_types ?? []).filter((t) => !disabled.has(t.key));
  const personalTypes = personal ? [...PERSONAL_OPTIONS, ...contributed.filter((t) => t.personal).map((t) => ({ value: t.key, label: t.label }))] : [];
  const sharedTypes = [...WIDGET_TYPE_OPTIONS, ...contributed.filter((t) => !t.personal).map((t) => ({ value: t.key, label: t.label }))];
  const own = isOwnType(type);
  const pickType = (next: string) => {
    setType(next);
    // Another type's config means nothing to this one; its form starts from an empty bag.
    setPluginConfig({});
    setPluginValid(true);
  };

  const ready = own ? isComplete(type, draft) && (!SLQ_TYPES.includes(type) || slqValid) : pluginValid;

  const save = useMutation({
    mutationFn: async () => {
      // The wire shape is the server's per-type schema; a plugin's config is its own bag.
      const config = (own ? configOf(type, draft) : pluginConfig) as WidgetConfig;
      const common = { title: title.trim() || null, width: Number(width), config };
      if (onDraft) {
        onDraft({ id: widget?.id ?? crypto.randomUUID(), widget_type: type, position: widget?.position ?? dashboard.widgets.length,
          height: widget?.height ?? 360, collapsed: widget?.collapsed ?? false, ...common });
        return;
      }
      if (widget) return api.patch<Dashboard>(dashboardWidgetPath(dashboard.id, widget.id), common satisfies DashboardWidgetUpdate);
      return api.post<Dashboard>(dashboardWidgetsPath(dashboard.id), {
        widget_type: type, position: dashboard.widgets.length, ...common,
      } satisfies DashboardWidgetCreate);
    },
    onSuccess: async () => {
      await invalidateEntities(queryClient, "dashboard");
      onClose();
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (ready) save.mutate();
  };
  // The server re-parses SLQ on save — a 422 here means the draft outran the live check.
  const saveSlqError = save.isError ? positionedErrorOf(save.error) : null;

  return (
    <Modal title={widget ? "Edit widget" : "Add widget"} onClose={onClose} wide>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <SelectField label="Type" value={type} onChange={(event) => pickType(event.target.value)} disabled={Boolean(widget)}
            hint={widget ? "Fixed — remove and re-add to change the type" : undefined}>
            {[...personalTypes, ...sharedTypes].map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </SelectField>
          <TextField label="Title (optional)" value={title} onChange={(event) => setTitle(event.target.value)}
            placeholder="Card label override" maxLength={200} />
        </div>
        {own ? (
          <WidgetConfigFields type={type} draft={draft} onChange={setDraft} onSlqValidity={setSlqValid} />
        ) : pluginForm ? (
          <>{pluginForm.contribution.render({ config: pluginConfig, onChange: setPluginConfig, onValidity: setPluginValid } satisfies DashboardWidgetConfigProps)}</>
        ) : null}
        <SelectField label="Width" value={width} onChange={(event) => setWidth(event.target.value)}
          hint="Columns out of 12. You can also drag to resize in edit mode.">
          {WIDTH_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </SelectField>
        {save.isError && !saveSlqError && <ErrorText error={save.error} />}
        {saveSlqError && <p className="text-xs text-status-danger-ink">Query rejected on save: {saveSlqError.message}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={!ready || save.isPending}>
            {save.isPending ? "Saving…" : widget ? "Save widget" : "Add widget"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
