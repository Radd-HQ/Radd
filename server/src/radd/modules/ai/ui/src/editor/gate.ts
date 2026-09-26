import { useQuery } from "@tanstack/react-query";
import { useIsAuthenticated } from "@radd/plugin-sdk";
import { aiEditorActionsQuery, aiPreferencesQuery, useAiStatus } from "../queries";
import { AiFeature, type AiEditorAction } from "../types";

/** Per-user opt-out in the spec-94 preferences dict — an absent key means enabled. */
export const EDITOR_AI_PREF_KEY = "ai.editor_actions";

/** One dispatchable AI run plus the label the run band shows: a curated action goes by id (the
 * server owns its prompt), typed text as the instruction. */
export type AiRun = { label: string } & ({ actionId: string } | { instruction: string });

/** A curated menu action as a dispatchable run. */
export function actionRun(action: AiEditorAction): AiRun {
  return { actionId: action.id, label: action.label };
}

interface EditorAi {
  actions: AiEditorAction[];
}

/**
 * Non-null only when the instance feature is on, the user has not opted out (Profile) AND the
 * actions have arrived — so the chrome appears once. Any fetch failure reads as off; a visitor
 * asks nothing (a 401 would redirect to /login).
 */
export function useEditorAi(): EditorAi | null {
  const signedIn = useIsAuthenticated();
  const status = useAiStatus();
  const prefs = useQuery({ ...aiPreferencesQuery, enabled: signedIn });
  const gateOpen =
    signedIn &&
    status.data?.features[AiFeature.editorActions] === true &&
    prefs.data !== undefined &&
    prefs.data[EDITOR_AI_PREF_KEY] !== false;
  const actions = useQuery({ ...aiEditorActionsQuery, enabled: gateOpen });
  if (!gateOpen || !actions.data) return null;
  return { actions: actions.data };
}
