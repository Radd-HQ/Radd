import { useQuery } from "@tanstack/react-query";
import type { EditorView } from "@milkdown/kit/prose/view";
import { iconOrFallback } from "../../lib/icons";
import { pageExtensionsQuery } from "../../lib/queries";
import type { PageExtensionSpec } from "../../lib/types";
import { configOnInsertKey, RADD_EXTENSION_NODE } from "./extension-node";

/**
 * The entries, grouped by the plugin that contributed them.
 *
 * By CONTRIBUTOR, not "built in versus plugin". That split was the first cut and
 * it was wrong twice over: `core` means "cannot be disabled" rather than "ships
 * with Radd" (`pages` is itself `core=false`, so every first-party extension
 * landed under a plugin heading), and development rule 1 says everything IS a
 * plugin — so the distinction was being manufactured rather than reported.
 *
 * Headings appear only once there is more than one contributor. With a single
 * one they would label the entire list, which tells nobody anything.
 */
function groupsOf(specs: PageExtensionSpec[]) {
  const byPlugin = new Map<string, PageExtensionSpec[]>();
  for (const spec of specs) {
    const key = spec.source || "Other";
    byPlugin.set(key, [...(byPlugin.get(key) ?? []), spec]);
  }
  const many = byPlugin.size > 1;
  return [...byPlugin].map(([plugin, entries]) => ({
    title: plugin.replace(/[_-]+/g, " ").replace(/^./, (c) => c.toUpperCase()),
    specs: entries,
    showTitle: many,
  }));
}

/**
 * The editor's insert menu for page extensions (RADD-709).
 *
 * The list comes from `GET /pages/extensions`, i.e. from the kernel registry —
 * not from a constant in the SPA. That is the whole point: a plugin that
 * contributes a `PageExtensionSpec` appears here in a running Radd with no
 * frontend change, and disabling that plugin removes it again.
 */
/** Kept for the render proofs, which look for `svg.radd-extension-toolbar-icon`.
 *  The toolbar itself renders a lucide component now (RADD-749); this was the
 *  markup a third-party toolbar builder demanded when it took strings. */
export const EXTENSION_TOOLBAR_ICON = `
  <svg xmlns="http://www.w3.org/2000/svg" class="radd-extension-toolbar-icon" width="24" height="24" viewBox="0 0 24 24">
    <path
      fill="currentColor"
      d="M5 4h6v3.2a2.3 2.3 0 1 1 2 0V4h6v6h-3.2a2.3 2.3 0 1 0 0 4H19v6h-6v-3.2a2.3 2.3 0 1 0-2 0V20H5v-6h3.2a2.3 2.3 0 1 0 0-4H5V4z"
    />
  </svg>
`;

export function ExtensionPicker({
  at,
  onPick,
}: {
  at: { left: number; top: number };
  /** Dispatched through the live editor by the caller — the same route the AI
   *  popover takes, rather than holding a view reference here. */
  onPick: (spec: PageExtensionSpec) => void;
}) {
  const { data, isLoading } = useQuery(pageExtensionsQuery);
  const insert = onPick;

  return (
    <div
      // z-[60] deliberately: the click-away overlay behind it is z-[59]. At
      // z-50 the overlay sat ON TOP of this menu and swallowed the mousedown,
      // so a real click closed the menu and inserted nothing — while a
      // synthesised .click() in the proof bypassed hit-testing and "passed".
      className="fixed z-[60] w-72 overflow-hidden rounded-lg border border-strong bg-overlay shadow-modal animate-menu-in"
      style={{ left: at.left, top: at.top }}
      role="menu"
    >
      <p className="border-b border-subtle px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-fg-muted">
        Insert extension
      </p>
      {isLoading ? (
        <p className="px-3 py-2 text-[13px] text-fg-faint">Loading…</p>
      ) : !data?.length ? (
        <p className="px-3 py-2 text-[13px] text-fg-faint">No extensions are installed.</p>
      ) : (
        <ul className="max-h-96 overflow-y-auto py-1">
          {groupsOf(data).map((group) => (
            <li key={group.title}>
              {/* A heading only once there is something to separate. With
                  built-ins alone it would be a label on the whole list. */}
              {group.showTitle && (
                <p className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-fg-faint">
                  {group.title}
                </p>
              )}
              <ul>
                {group.specs.map((spec) => {
                  const Icon = iconOrFallback(spec.icon);
                  return (
                    <li key={spec.name}>
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => insert(spec)}
                        title={spec.description}
                        className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left hover:bg-elevated cursor-pointer"
                      >
                        <Icon size={15} className="shrink-0 text-fg-muted" aria-hidden />
                        <span className="flex min-w-0 flex-col">
                          <span className="text-[13px] leading-tight text-heading">
                            {spec.label}
                          </span>
                          {spec.description && (
                            <span className="truncate text-[11px] leading-tight text-fg-muted">
                              {spec.description}
                            </span>
                          )}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Insert `radd:<name>` at the cursor, pre-filled with the schema's defaults.
 *
 * Pre-filling matters more than it looks: an empty block is valid but tells the
 * author nothing about what they may set. Since RADD-746 the block also RENDERS
 * where it is inserted, so the defaults are visible as a result rather than as
 * JSON — which is what makes "insert, then adjust" a reasonable order of work.
 *
 * The `code_block` fallback is not dead code: it is what a surface WITHOUT the
 * extension node (the picker is opt-in per surface) would produce, and it emits
 * the identical fence — the same honest degradation the wire format has.
 */
export function insertExtensionBlock(view: EditorView, spec: PageExtensionSpec): void {
  const { state } = view;
  const params = defaultsFor(spec);
  const body = Object.keys(params).length ? JSON.stringify(params, null, 2) : "";
  const extension = state.schema.nodes[RADD_EXTENSION_NODE];
  const codeBlock = state.schema.nodes.code_block;
  const node = extension
    ? extension.create({ name: spec.name, body })
    : codeBlock
      ? codeBlock.create(
          { language: `radd:${spec.name}` },
          body ? state.schema.text(body) : null,
        )
      : null;
  if (!node) return;
  const tr = state.tr.replaceSelectionWith(node).scrollIntoView();
  // Ask the new block to open its config form (RADD-747). The position is found
  // by node IDENTITY rather than arithmetic on the selection: `replaceSelectionWith`
  // may replace an empty parent paragraph instead of inserting inside it, so
  // "selection minus nodeSize" is right only some of the time.
  let inserted = -1;
  tr.doc.descendants((candidate, pos) => {
    if (candidate === node) {
      inserted = pos;
      return false;
    }
    return inserted === -1;
  });
  if (inserted >= 0) tr.setMeta(configOnInsertKey, inserted);
  view.dispatch(tr);
  view.focus();
}

/** Required properties, plus any that declare a default. */
function defaultsFor(spec: PageExtensionSpec): Record<string, unknown> {
  const properties = (spec.params_schema?.properties ?? {}) as Record<
    string,
    { default?: unknown; type?: string; enum?: unknown[] }
  >;
  const required = new Set(spec.params_schema?.required ?? []);
  const out: Record<string, unknown> = {};
  for (const [key, property] of Object.entries(properties)) {
    if (property.default !== undefined) out[key] = property.default;
    else if (required.has(key)) out[key] = property.enum?.[0] ?? placeholderFor(property.type);
  }
  return out;
}

const placeholderFor = (type: string | undefined) =>
  type === "integer" || type === "number" ? 0 : type === "boolean" ? false : "";
