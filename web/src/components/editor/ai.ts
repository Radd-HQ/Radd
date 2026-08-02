import { useQuery } from "@tanstack/react-query";
import type { AIProvider, AISuggestionsBuilder } from "@milkdown/crepe/feature/ai";
import { commandsCtx, editorViewCtx } from "@milkdown/kit/core";
import type { Ctx } from "@milkdown/kit/ctx";
import { TextSelection } from "@milkdown/kit/prose/state";
import { ApiPath } from "../../lib/constants";
import { aiEditorActionsQuery, aiStatusQuery, mePreferencesQuery } from "../../lib/queries";
import { streamSse } from "../../lib/sse";
import { AiEditorActionKind, AiFeature, type AiEditorAction } from "../../lib/types";

/**
 * Editor AI (spec 103): Crepe's built-in AI feature wired to the backend's
 * curated actions + SSE stream. The suggestion menu is server-defined —
 * builtins plus admin presets — so a menu pick must send its ACTION ID (the
 * server owns the prompt text). Crepe only carries a `prompt` string through
 * its menu, so ids ride in-band behind a sentinel prefix; an instruction the
 * user typed freely (no prefix) goes up verbatim as `instruction`.
 */

/** Marks a Crepe suggestion "prompt" as a server action id, not instruction text. */
export const INSTRUCTION_ACTION_PREFIX = "#radd-action:";

/** Per-user opt-out in the spec-94 preferences dict — an absent key means enabled. */
export const EDITOR_AI_PREF_KEY = "ai.editor_actions";

/** Streams from POST /ai/editor/stream, unpacking the sentinel (see module doc). */
export function createAiProvider(): AIProvider {
  return ({ document, selection, instruction }, signal) =>
    streamSse(
      ApiPath.aiEditorStream,
      instruction.startsWith(INSTRUCTION_ACTION_PREFIX)
        ? { action_id: instruction.slice(INSTRUCTION_ACTION_PREFIX.length), document, selection }
        : { instruction, document, selection },
      signal,
    );
}

// Crepe menu icons are raw 24×24 currentColor SVG strings (the same shape as
// its stock icons): sparkles = shipped builtin, bookmark = admin preset.
const BUILTIN_ICON = `
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
    <path
      fill="currentColor"
      d="M9 3.5l1.6 4.4L15 9.5l-4.4 1.6L9 15.5 7.4 11.1 3 9.5l4.4-1.6L9 3.5zm8.5 7.5l1.1 3 3 1.1-3 1.1-1.1 3-1.1-3-3-1.1 3-1.1 1.1-3z"
    />
  </svg>
`;
const PRESET_ICON = `
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
    <path
      fill="currentColor"
      d="M6.5 3h11A1.5 1.5 0 0 1 19 4.5V21l-7-3.7L5 21V4.5A1.5 1.5 0 0 1 6.5 3z"
    />
  </svg>
`;

/** The TopBar AI button's icon. The marker class is how RichEditor finds the
 * rendered button again to anchor its React popover — Crepe's TopBar is Vue
 * and its item API hands back no DOM node. */
export const AI_TOOLBAR_ICON = `
  <svg xmlns="http://www.w3.org/2000/svg" class="radd-ai-toolbar-icon" width="24" height="24" viewBox="0 0 24 24">
    <path
      fill="currentColor"
      d="M9 3.5l1.6 4.4L15 9.5l-4.4 1.6L9 15.5 7.4 11.1 3 9.5l4.4-1.6L9 3.5zm8.5 7.5l1.1 3 3 1.1-3 1.1-1.1 3-1.1-3-3-1.1 3-1.1 1.1-3z"
    />
  </svg>
`;

/** Replaces Crepe's stock prompt menu with the server's curated actions. */
export function buildSuggestions(
  actions: AiEditorAction[],
): (builder: AISuggestionsBuilder) => void {
  return (builder) => {
    builder.clear(); // stock prompts (improve/tone/…) — the server list replaces them
    for (const action of actions) {
      builder.addItem(action.id, {
        icon: action.kind === AiEditorActionKind.preset ? PRESET_ICON : BUILTIN_ICON,
        label: action.label,
        streamingLabel: `${action.label}…`,
        prompt: INSTRUCTION_ACTION_PREFIX + action.id,
      });
    }
  };
}

/** One dispatchable AI transform: the wire instruction (sentinel-prefixed
 * action id, or freeform text) plus the label the streaming indicator shows. */
export interface AiRun {
  instruction: string;
  label: string;
}

/** A curated menu action as a dispatchable run. */
export function actionRun(action: AiEditorAction): AiRun {
  return { instruction: INSTRUCTION_ACTION_PREFIX + action.id, label: action.label };
}

/** Crepe's RunAI command, dispatched BY NAME: importing `runAICmd` from
 * "@milkdown/crepe/feature/ai" binds a SECOND copy of the feature module (the
 * package bundles its features into the root entry AND each subpath entry),
 * and a $command's `.key` is only assigned when its plugin instance runs —
 * which only the root entry's copy does. The registered command name is the
 * stable cross-instance handle. */
const RUN_AI_COMMAND = "RunAI";

/**
 * Run an AI transform over the current selection — or the WHOLE document when
 * nothing is selected (the toolbar button and the read-mode menu, which have
 * no anchor selection). The stream lands as the usual reviewable diff. False
 * when the editor can't take a run right now (an AI session or diff review is
 * already active).
 */
export function runAiOnEditor(ctx: Ctx, run: AiRun): boolean {
  const view = ctx.get(editorViewCtx);
  const { state } = view;
  if (state.selection.empty) {
    const all = TextSelection.between(
      state.doc.resolve(0),
      state.doc.resolve(state.doc.content.size),
    );
    view.dispatch(state.tr.setSelection(all));
  }
  return ctx.get(commandsCtx).call(RUN_AI_COMMAND, { ...run });
}

export interface EditorAi {
  actions: AiEditorAction[];
}

/**
 * The editor-AI gate: non-null only when the instance feature is on
 * (aiStatus.features.editor_actions), the user hasn't opted out
 * (Settings → Profile), AND the action list has arrived — so the editor
 * mounts its AI chrome exactly once instead of recreating as pieces trickle
 * in. Any fetch failure (404 dormant included) reads as "off".
 *
 * `enabled: false` (the anonymous public form) mounts NO queries at all:
 * every one of them is authenticated, and the api client answers a 401 with
 * a redirect to /login — which must never happen to an anonymous visitor.
 */
export function useEditorAi(enabled = true): EditorAi | null {
  const status = useQuery({ ...aiStatusQuery, enabled });
  const prefs = useQuery({ ...mePreferencesQuery(), enabled });
  const gateOpen =
    enabled &&
    // `features` is optional-chained deliberately: a pre-spec-101 backend
    // returns {enabled, provider, model} with no features map at all.
    status.data?.features?.[AiFeature.editorActions] === true &&
    prefs.data !== undefined &&
    prefs.data[EDITOR_AI_PREF_KEY] !== false;
  const actions = useQuery({ ...aiEditorActionsQuery, enabled: gateOpen });
  if (!gateOpen || !actions.data) return null;
  return { actions: actions.data };
}
