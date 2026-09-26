import { Suspense, lazy, type ReactNode } from "react";
import { ExtensionCard, registerPageExtension, type PageExtension } from "@radd/plugin-sdk";

/**
 * The first-party `radd:*` extensions, registered at boot: a block renders wherever markdown does, so
 * registration is eager while renderers load with the first block that needs one (PageBody imports
 * them directly). `tests/test_page_extensions.py` matches this list to the kernel's, both ways.
 */

export type ExtensionRenderers = Record<string, (params: Record<string, unknown>) => ReactNode>;

let renderers: ExtensionRenderers | null = null;

/** Called by the renderer modules as they load. */
export function provideExtensionRenderers(next: ExtensionRenderers): void {
  renderers = { ...renderers, ...next };
}

interface BlockProps { name: string; params: Record<string, unknown> }

function Rendered({ name, params }: BlockProps) {
  return <>{renderers?.[name]?.(params)}</>;
}

const Loaded = lazy(() => import("./view/extensions").then(() => ({ default: Rendered })));

function FirstParty(props: BlockProps) {
  if (renderers?.[props.name]) return <Rendered {...props} />;
  return (
    <Suspense fallback={<ExtensionCard label={`radd:${props.name}`}><span className="text-[13px] text-fg-faint">Loading…</span></ExtensionCard>}>
      <Loaded {...props} />
    </Suspense>
  );
}

const firstParty = (name: string, label: string, description: string): PageExtension => ({
  name, label, description, render: (params) => <FirstParty name={name} params={params} />,
});

const EXTENSIONS: PageExtension[] = [
  firstParty("toc", "Table of contents", "This page's headings, optionally with the pages beneath it."),
  firstParty("children", "Child pages", "A list of the pages directly beneath this one."),
  firstParty("callout", "Callout", "A tinted note: info, success, warning or danger."),
  firstParty("backlinks", "Backlinks", "Every page that links to this one."),
  firstParty("include", "Include a page", "Render another page's body inline, live."),
  firstParty("label-list", "Pages by label", "Every page carrying a label — an index that maintains itself."),
  firstParty("new-from-template", "New page from template", "A button that creates a child page from a template."),
  // Spec 117: the importers' blocks.
  firstParty("media", "Video or audio", "Play an attached video or audio file in the page."),
  firstParty("unsupported-macro", "Unsupported macro", "An imported macro Radd cannot render yet, kept verbatim."),
  firstParty("expand", "Expand", "A collapsible section."),
  firstParty("items", "Issue query", "Issues matching an SLQ query, as a table."),
];

export function registerPageExtensions(): void {
  for (const extension of EXTENSIONS) registerPageExtension(extension);
}
