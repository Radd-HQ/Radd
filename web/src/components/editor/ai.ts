import { useQuery } from "@tanstack/react-query";
import { aiEditorActionsQuery, aiStatusQuery, mePreferencesQuery } from "../../lib/queries";
import { AiFeature, type AiEditorAction } from "../../lib/types";

/**
 * Editor AI (spec 103), as the app defines it.
 *
 * The suggestion menu is server-defined — builtins plus admin presets — so a
 * menu pick sends its ACTION ID and the server owns the prompt text. The
 * sentinel prefix survives from when a third-party menu could only carry a
 * `prompt` STRING through to the provider; it is still the cheapest way to say
 * "this is an id, not something a person typed", and `ai-run.ts` unpacks it into
 * the request's `action_id` or `instruction` accordingly.
 *
 * What used to live here and no longer does (RADD-753): the provider adapter,
 * the suggestion-menu builder with its raw-SVG icons, and a command dispatched
 * by NAME to dodge a duplicate module instance. The orchestration is ours now —
 * see `ai-run.ts` — so none of those seams exist to be worked around.
 */

/** Marks an instruction string as a server action id rather than typed text. */
export const INSTRUCTION_ACTION_PREFIX = "#radd-action:";

/** Per-user opt-out in the spec-94 preferences dict — an absent key means enabled. */
export const EDITOR_AI_PREF_KEY = "ai.editor_actions";

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
