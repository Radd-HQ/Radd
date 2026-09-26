import { useMemo, type ReactNode } from "react";
import type { ContentContext } from "./editor-extensions";
import type { PluginContribution } from "./plugin";
import { SlotId, useSlot } from "./slots";

/**
 * Content bodies (RADD-1401): how a rendered body — an issue's description, a comment, a reply —
 * is DRAWN when a plugin owns part of its presentation. The host draws every body with its own
 * viewer; a plugin that knows something about some bodies (mail knows a mailed one ends in a
 * signature it folded away) CLAIMS them by their record and draws them instead, through the
 * host's viewer for the text itself.
 *
 * Nothing here is a new registry: a body contribution is an ordinary slot contribution
 * (`SlotId.contentBody`, keyed by `match` = its id — plugin tagging, withdrawal, the toggles and the
 * error boundary come with it) whose `meta` carries the claim. Without a claimant, or when its
 * plugin is withdrawn, the body is the host's ordinary markdown; a claimant that throws while
 * drawing falls back to it too.
 */

/** `content.body` props. */
export interface ContentBodyProps {
  /** The body's markdown, as stored. */
  text: string;
  /** The row the body belongs to, as the server sent it — an issue, a comment, a reply, or a
   *  requester's view of one. It is what `claims` read; read the fields you claimed it by. */
  record: object;
  /** What the body is: an issue's description is `{entityType: "item"}`, a comment names its
   *  `parent`. */
  context: ContentContext;
  /** Whether this reader may change the content — its author, someone who runs the project. */
  canEdit: boolean;
  /** Draw markdown exactly as the host draws this body (its viewer, deferred mounting, mentions,
   *  checklists). A LEADING part keeps the body's task checkboxes live; any other part is drawn
   *  read-only, since its tasks are not counted from the body's start. */
  renderText: (text: string) => ReactNode;
}

export interface ContentBodySpec {
  /** `<plugin>.<name>` of the registering plugin; another prefix is refused. */
  id: string;
  /** Names the contribution in the toggle lists. */
  label: string;
  /** Whether this plugin draws the body of `record`. Called for every body the host renders, so
   *  keep it a cheap, pure read of the record; a throw counts as no. */
  claims: (record: object) => boolean;
  render: (props: ContentBodyProps) => ReactNode;
}

/** The contribution row for `definePlugin({ contributions: [contentBody({...})] })`. */
export function contentBody(spec: ContentBodySpec): PluginContribution {
  const { render, ...meta } = spec;
  return {
    id: `body:${spec.id}`,
    slot: SlotId.contentBody,
    match: spec.id,
    label: spec.label,
    meta,
    render: (props) => render(props as unknown as ContentBodyProps),
  };
}

/** Which contribution draws a body: its `match` and its owner, for `<Slot match owner>`. */
export interface ContentBodyClaim {
  id: string;
  plugin: string;
}

function claimOf(plugin: string, match: string | undefined, meta: Readonly<Record<string, unknown>> | undefined) {
  if (!meta || typeof meta.id !== "string" || meta.id !== match || typeof meta.claims !== "function") return null;
  const prefix = `${plugin}.`;
  if (!meta.id.startsWith(prefix) || meta.id.length === prefix.length) return null;
  return meta.claims as (record: object) => boolean;
}

/** The contribution that draws `record`'s body — the first registered, turned-on one (in `order`)
 *  whose claim holds — or null, and the host draws it. */
export function useContentBodyClaim(record: object): ContentBodyClaim | null {
  const entries = useSlot(SlotId.contentBody);
  return useMemo(() => {
    for (const entry of entries) {
      const claims = claimOf(entry.plugin, entry.contribution.match, entry.contribution.meta);
      if (!claims) continue;
      let claimed = false;
      try {
        claimed = claims(record) === true;
      } catch {
        claimed = false;
      }
      if (claimed) return { id: entry.contribution.match as string, plugin: entry.plugin };
    }
    return null;
  }, [entries, record]);
}
