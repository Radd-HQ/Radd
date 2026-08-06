/**
 * The right-click node menu (spec 116, RADD-916) — Nuke's tab-menu idea.
 *
 * Right-click empty canvas, type, Enter. That is the fast path once someone
 * knows the node they want, and it beats hunting a list. It reads the SAME
 * catalogue the panel does, so the two can never offer different things.
 *
 * Keyboard first: it opens focused, arrows move, Enter adds at the click point,
 * Escape closes. A context menu you must reach for the mouse to finish is not
 * faster than the list it replaces.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { searchTemplates, type NodeTemplate } from "../../lib/automation-nodes";
import { NODE_KIND_ICON, NODE_KIND_TONE } from "./node-visuals";

interface NodeSearchMenuProps {
  templates: NodeTemplate[];
  /** Where the user right-clicked, in viewport coordinates. */
  at: { x: number; y: number };
  onPick: (template: NodeTemplate) => void;
  onClose: () => void;
}

const MENU_WIDTH = 280;
const MENU_MAX_HEIGHT = 340;

export function NodeSearchMenu({ templates, at, onPick, onClose }: NodeSearchMenuProps) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const matches = useMemo(() => searchTemplates(templates, query).slice(0, 60), [templates, query]);

  useEffect(() => setActive(0), [query]);
  useEffect(() => inputRef.current?.focus(), []);

  // Clamp inside the viewport. A menu opened near the right or bottom edge would
  // otherwise render half off-screen, which is exactly where people right-click
  // when the canvas is full.
  const [position, setPosition] = useState(at);
  useLayoutEffect(() => {
    setPosition({
      x: Math.min(at.x, window.innerWidth - MENU_WIDTH - 8),
      y: Math.min(at.y, window.innerHeight - MENU_MAX_HEIGHT - 8),
    });
  }, [at]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!listRef.current?.closest("[data-node-menu]")?.contains(event.target as Node)) onClose();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, [onClose]);

  const move = (delta: number) => {
    setActive((current) => {
      if (matches.length === 0) return 0;
      const next = (current + delta + matches.length) % matches.length;
      listRef.current?.children[next]?.scrollIntoView({ block: "nearest" });
      return next;
    });
  };

  return (
    <div
      data-node-menu
      role="dialog"
      aria-label="Add a node"
      style={{ left: position.x, top: position.y, width: MENU_WIDTH }}
      className="fixed z-50 overflow-hidden rounded-[10px] border border-strong bg-overlay shadow-modal animate-menu-in"
    >
      <input
        ref={inputRef}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            move(1);
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            move(-1);
          } else if (event.key === "Enter") {
            event.preventDefault();
            const picked = matches[active];
            if (picked) onPick(picked);
          }
        }}
        placeholder="Add a node…"
        aria-label="Search nodes"
        className="h-9 w-full border-b border-subtle bg-transparent px-3 text-[13px] text-fg outline-none placeholder:text-fg-faint"
      />
      <ul ref={listRef} className="max-h-[300px] overflow-y-auto py-1">
        {matches.length === 0 && (
          <li className="px-3 py-3 text-center text-xs text-fg-muted">Nothing matches “{query}”.</li>
        )}
        {matches.map((template, index) => {
          const Icon = NODE_KIND_ICON[template.kind];
          return (
            <li key={template.key}>
              <button
                type="button"
                onMouseEnter={() => setActive(index)}
                onClick={() => onPick(template)}
                className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] cursor-pointer ${
                  index === active ? "bg-elevated text-heading" : "text-fg"
                }`}
              >
                <Icon
                  size={12}
                  className="shrink-0"
                  style={{ color: NODE_KIND_TONE[template.kind] }}
                  aria-hidden
                />
                <span className="truncate">{template.label}</span>
                <span className="ml-auto shrink-0 text-[10px] uppercase tracking-wide text-fg-faint">
                  {template.group.replace(/^Triggers · /, "")}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
