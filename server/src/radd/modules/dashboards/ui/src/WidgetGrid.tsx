import { useEffect, useRef, type CSSProperties, type ReactNode, type PointerEvent } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, GripVertical, Pencil, Trash2 } from "lucide-react";
import { ChartHeightContext, useCapabilities } from "@radd/plugin-sdk";
import type { DashboardWidget } from "./types";
import { CARD_LABELS } from "./widget-meta";

export function WidgetGrid({ widgets, editing, onChange, onConfigure, onCollapse, render }: {
  widgets: DashboardWidget[]; editing: boolean;
  onChange: (widgets: DashboardWidget[]) => void;
  onConfigure: (widget: DashboardWidget) => void;
  onCollapse: (widget: DashboardWidget) => void;
  render: (widget: DashboardWidget) => ReactNode;
}) {
  const root = useRef<HTMLDivElement>(null);
  const cleanup = useRef<(() => void) | null>(null);
  useEffect(() => () => cleanup.current?.(), []);
  // A contributed type is named by its plugin's label.
  const contributed = useCapabilities()?.widget_types ?? [];
  const nameOf = (widget: DashboardWidget) => widget.title || CARD_LABELS[widget.widget_type]
    || contributed.find((t) => t.key === widget.widget_type)?.label || widget.widget_type.replaceAll("_", " ");
  const patch = (id: string, change: Partial<DashboardWidget>) => onChange(widgets.map(w => w.id === id ? { ...w, ...change } : w));
  const move = (from: number, to: number) => {
    if (to < 0 || to >= widgets.length || from === to) return;
    const copy = [...widgets]; copy.splice(to, 0, copy.splice(from, 1)[0]); onChange(copy);
  };
  const gesture = (event: PointerEvent, widget: DashboardWidget, mode: "move" | "width" | "height" | "both") => {
    if (!editing || event.button !== 0) return;
    event.preventDefault();
    const startX = event.clientX, startY = event.clientY;
    const column = ((root.current?.clientWidth ?? 1200) + 12) / 12;
    let next = widgets;
    const motion = (e: globalThis.PointerEvent) => {
      if (mode === "move") {
        const target = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-widget-id]");
        if (!target) return;
        const to = next.findIndex(w => w.id === target.dataset.widgetId), from = next.findIndex(w => w.id === widget.id);
        if (to < 0 || from === to) return;
        next = [...next]; next.splice(to, 0, next.splice(from, 1)[0]);
      } else {
        const width = mode === "height" ? widget.width : Math.min(12, Math.max(2, widget.width + Math.round((e.clientX - startX) / column)));
        const height = mode === "width" ? widget.height : Math.min(1600, Math.max(160, Math.round((widget.height + e.clientY - startY) / 20) * 20));
        next = widgets.map(w => w.id === widget.id ? { ...w, width, height } : w);
      }
      onChange(next);
    };
    const finish = () => { window.removeEventListener("pointermove", motion); window.removeEventListener("pointerup", finish); window.removeEventListener("pointercancel", cancel); cleanup.current = null; };
    const cancel = () => { onChange(widgets); finish(); };
    cleanup.current?.(); cleanup.current = finish;
    window.addEventListener("pointermove", motion); window.addEventListener("pointerup", finish); window.addEventListener("pointercancel", cancel);
  };
  return <div ref={root} className="widget-grid">
    {widgets.map((widget, index) => <section key={widget.id} data-widget-id={widget.id} data-widget-type={widget.widget_type} data-collapsed={widget.collapsed || undefined}
      style={{ "--widget-width": widget.width, "--widget-height": `${widget.height}px` } as CSSProperties}
      className="dashboard-widget relative flex min-w-0 flex-col rounded-lg border border-subtle bg-surface">
      <header className="flex min-h-10 items-center gap-1 border-b border-subtle px-2">
        {editing && <button type="button" title="Drag to move; use arrow buttons to reorder" aria-label={`Move ${widget.title ?? widget.widget_type}`}
          className="touch-none cursor-grab p-1 text-fg-muted" onPointerDown={e => gesture(e, widget, "move")}><GripVertical size={16} /></button>}
        <button type="button" className="flex min-h-9 min-w-0 flex-1 items-center gap-1 text-left text-sm font-medium" aria-expanded={!widget.collapsed} onClick={() => onCollapse(widget)}>
          {widget.collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}<span className="truncate">{nameOf(widget)}</span>
        </button>
        {editing && <>
          <button type="button" aria-label="Move widget up" disabled={!index} onClick={() => move(index, index - 1)}><ArrowUp size={14} /></button>
          <button type="button" aria-label="Move widget down" disabled={index === widgets.length - 1} onClick={() => move(index, index + 1)}><ArrowDown size={14} /></button>
          <button type="button" aria-label="Configure widget" className="p-1" onClick={() => onConfigure(widget)}><Pencil size={14} /></button>
          <button type="button" aria-label="Remove widget" className="p-1" onClick={() => onChange(widgets.filter(w => w.id !== widget.id))}><Trash2 size={14} /></button>
        </>}
      </header>
      {!widget.collapsed && <div className="min-h-0 flex-1 overflow-auto p-3"><ChartHeightContext.Provider value={Math.max(160, widget.height - (editing ? 210 : 180))}>{render(widget)}</ChartHeightContext.Provider></div>}
      {editing && !widget.collapsed && <>
        <div className="flex items-center gap-2 border-t border-subtle px-3 py-1 text-xs">
          <label>Width <input aria-label="Widget width" className="w-12 bg-base" type="number" min={2} max={12} value={widget.width} onChange={e => patch(widget.id, { width: Math.max(2, Math.min(12, Number(e.target.value))) })} /></label>
          <label>Height <input aria-label="Widget height" className="w-16 bg-base" type="number" min={160} max={1600} step={20} value={widget.height} onChange={e => patch(widget.id, { height: Math.max(160, Math.min(1600, Number(e.target.value))) })} /></label>
        </div>
        <div aria-hidden className="absolute right-0 top-11 bottom-6 w-2 touch-none cursor-ew-resize" onPointerDown={e => gesture(e, widget, "width")} />
        <div aria-hidden className="absolute bottom-0 left-2 right-6 h-2 touch-none cursor-ns-resize" onPointerDown={e => gesture(e, widget, "height")} />
        <div aria-hidden className="absolute bottom-0 right-0 h-5 w-5 touch-none cursor-nwse-resize border-b-2 border-r-2 border-strong rounded-br-lg" onPointerDown={e => gesture(e, widget, "both")} />
      </>}
    </section>)}
  </div>;
}
