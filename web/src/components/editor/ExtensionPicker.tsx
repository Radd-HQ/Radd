import { useQuery } from "@tanstack/react-query";
import type { EditorView } from "@milkdown/prose/view";
import { pageExtensionsQuery } from "../../lib/queries";
import type { PageExtensionSpec } from "../../lib/types";

/**
 * The editor's insert menu for page extensions (RADD-709).
 *
 * The list comes from `GET /pages/extensions`, i.e. from the kernel registry —
 * not from a constant in the SPA. That is the whole point: a plugin that
 * contributes a `PageExtensionSpec` appears here in a running Radd with no
 * frontend change, and disabling that plugin removes it again.
 */
/** The TopBar button. A raw SVG string because Crepe's toolbar builder takes
 *  markup, not a component; the class is the handle the popover anchors to. */
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
  /** Dispatched through the live Crepe instance by the caller — the same route
   *  the AI popover takes, rather than holding a view reference here. */
  onPick: (spec: PageExtensionSpec) => void;
}) {
  const { data, isLoading } = useQuery(pageExtensionsQuery);
  const insert = onPick;

  return (
    <div
      className="fixed z-50 w-72 overflow-hidden rounded-lg border border-strong bg-overlay shadow-modal animate-menu-in"
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
        <ul className="max-h-80 overflow-y-auto py-1">
          {data.map((spec) => (
            <li key={spec.name}>
              <button
                type="button"
                role="menuitem"
                onClick={() => insert(spec)}
                className="flex w-full flex-col items-start gap-0.5 px-3 py-1.5 text-left hover:bg-elevated cursor-pointer"
              >
                <span className="text-[13px] text-heading">{spec.label}</span>
                {spec.description && (
                  <span className="text-[11px] text-fg-muted">{spec.description}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Insert ```` ```radd:<name> ```` at the cursor, pre-filled with the schema's
 * defaults.
 *
 * Pre-filling matters more than it looks: an empty block is valid but tells the
 * author nothing about what they may set, and the alternative — a parameter form
 * in the menu — asks people to fill in a dialog before they can see the thing
 * they are inserting. The defaults ARE the documentation, editable in place.
 */
export function insertExtensionBlock(view: EditorView, spec: PageExtensionSpec): void {
  const { state } = view;
  const codeBlock = state.schema.nodes.code_block;
  if (!codeBlock) return;
  const params = defaultsFor(spec);
  const text = Object.keys(params).length ? JSON.stringify(params, null, 2) : "";
  const node = codeBlock.create(
    { language: `radd:${spec.name}` },
    text ? state.schema.text(text) : null,
  );
  view.dispatch(state.tr.replaceSelectionWith(node).scrollIntoView());
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
