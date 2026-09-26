import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ErrorText } from "@radd/plugin-sdk";
import { EDITOR_AI_PREF_KEY } from "../editor/gate";
import { aiPreferencesQuery } from "../queries";
import { AiEndpoint } from "../transport";

/**
 * The editor-AI opt-out (specs 101/103) — this plugin's `profile.section` (RADD-1395). Stored
 * server-side in the preferences dict (spec 94 shallow-merge PUT) so it follows the account across
 * browsers; an absent key means enabled, and the editor gate (`editor/gate.ts`) reads the same one.
 */
export function EditorAiPreference() {
  const queryClient = useQueryClient();
  const prefs = useQuery(aiPreferencesQuery);
  const save = useMutation({
    mutationFn: (enabled: boolean) =>
      api.put<Record<string, unknown>>(AiEndpoint.mePreferences, { [EDITOR_AI_PREF_KEY]: enabled }),
    onSuccess: (data) => queryClient.setQueryData(aiPreferencesQuery.queryKey, data),
  });

  return (
    <section className="mt-8 border-t border-subtle pt-6" data-ai-profile>
      <h2 className="mb-1 text-sm font-semibold text-fg">AI assistance</h2>
      <p className="mb-4 text-xs text-fg-muted">
        Personal opt-out for the editor's AI menu. Whether the feature exists at all is an instance
        setting (Settings → AI).
      </p>
      {prefs.isPending ? (
        <p className="text-xs text-fg-faint">Loading preferences…</p>
      ) : prefs.isError ? (
        <ErrorText error={prefs.error} />
      ) : (
        <div className="flex flex-col gap-2">
          <label className="flex items-center gap-2 text-[13px] text-fg">
            <input
              type="checkbox"
              checked={prefs.data[EDITOR_AI_PREF_KEY] !== false}
              onChange={() => save.mutate(prefs.data[EDITOR_AI_PREF_KEY] === false)}
              disabled={save.isPending}
              className="size-3.5 accent-accent"
            />
            AI writing actions in the editor
          </label>
          {save.isError && <ErrorText error={save.error} />}
        </div>
      )}
    </section>
  );
}
