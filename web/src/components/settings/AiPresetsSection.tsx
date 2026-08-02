import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2, WandSparkles, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, apiAiPresetPath } from "../../lib/constants";
import { aiPresetsQuery, queryKeys } from "../../lib/queries";
import { type AiPreset } from "../../lib/types";
import { Button } from "../Button";
import { EmptyState } from "../EmptyState";
import { QueryError } from "../QueryError";
import { TableSkeleton } from "../TableSkeleton";
import { TextField } from "../TextField";

const sectionHeadClasses = "mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted";

/**
 * The editor-action prompt library (spec 101; the spec-103 editor menu consumes
 * it). Enabled presets appear as named actions in every user's editor AI menu —
 * the prompt text itself stays server-side, never shipped to the browser.
 */
export function AiPresetsSection() {
  const presets = useQuery(aiPresetsQuery());
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<AiPreset | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.aiPresets });
  const remove = useMutation({
    mutationFn: (presetId: string) => api.delete<void>(apiAiPresetPath(presetId)),
    onSettled: invalidate,
  });
  const toggle = useMutation({
    mutationFn: (preset: AiPreset) =>
      api.patch<AiPreset>(apiAiPresetPath(preset.id), { enabled: !preset.enabled }),
    onSettled: invalidate,
  });

  const list = presets.data ?? [];

  return (
    <section>
      <h2 className={sectionHeadClasses}>Editor presets</h2>
      <p className="mb-3 text-xs text-fg-muted">
        Named prompts offered as actions in every user's editor AI menu, alongside the built-ins.
        The prompt runs server-side against the selection — users see only the name.
      </p>
      {presets.isPending ? (
        <TableSkeleton rows={2} />
      ) : presets.isError ? (
        <QueryError label="AI presets" error={presets.error} />
      ) : (
        <>
          {list.length === 0 ? (
            <EmptyState
              icon={WandSparkles}
              message="No presets yet — try one like “Make it release-note ready”."
            />
          ) : (
            <ul className="rounded-lg border border-subtle">
              {list.map((preset) => (
                <li
                  key={preset.id}
                  className="border-b border-subtle/60 px-4 py-2.5 last:border-b-0"
                >
                  <div className="flex items-center gap-2">
                    <label
                      className="flex items-center gap-2 text-xs text-fg-muted"
                      title={preset.enabled ? "Shown in the editor AI menu" : "Hidden from the menu"}
                    >
                      <input
                        type="checkbox"
                        checked={preset.enabled}
                        onChange={() => toggle.mutate(preset)}
                        disabled={toggle.isPending}
                        className="size-3.5 accent-accent"
                      />
                    </label>
                    <span
                      className={
                        "flex-1 text-[13px] font-medium " +
                        (preset.enabled ? "text-heading" : "text-fg-faint")
                      }
                    >
                      {preset.name}
                    </span>
                    <button
                      type="button"
                      onClick={() => setEditing(editing?.id === preset.id ? null : preset)}
                      aria-label={`Edit ${preset.name}`}
                      className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
                    >
                      <Pencil size={13} aria-hidden />
                    </button>
                    <button
                      type="button"
                      onClick={() => remove.mutate(preset.id)}
                      aria-label={`Delete ${preset.name}`}
                      className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-red-300 cursor-pointer"
                    >
                      <Trash2 size={13} aria-hidden />
                    </button>
                  </div>
                  <p className="mt-0.5 line-clamp-2 whitespace-pre-wrap text-xs text-fg-muted">
                    {preset.prompt}
                  </p>
                  {editing?.id === preset.id && (
                    <PresetForm existing={preset} onDone={() => setEditing(null)} />
                  )}
                </li>
              ))}
            </ul>
          )}
          <PresetForm nextPosition={list.length} />
        </>
      )}
      {remove.isError && (
        <p className="mt-2 text-xs text-red-400">{errorMessage(remove.error)}</p>
      )}
    </section>
  );
}

function PresetForm({
  existing,
  nextPosition = 0,
  onDone,
}: {
  existing?: AiPreset;
  nextPosition?: number;
  onDone?: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(existing?.name ?? "");
  const [prompt, setPrompt] = useState(existing?.prompt ?? "");

  const save = useMutation({
    mutationFn: () =>
      existing
        ? api.patch<AiPreset>(apiAiPresetPath(existing.id), { name, prompt })
        : api.post<AiPreset>(ApiPath.aiPresets, {
            name,
            prompt,
            enabled: true,
            position: nextPosition,
          }),
    onSuccess: () => {
      if (!existing) {
        setName("");
        setPrompt("");
      }
      onDone?.();
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.aiPresets }),
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim() && prompt.trim()) save.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="mt-4 flex flex-col gap-3">
      <TextField
        label={existing ? "Name" : "New preset name"}
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="Make it release-note ready"
        maxLength={200}
      />
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-fg-secondary">Prompt</label>
        <textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          rows={3}
          placeholder="Rewrite the selection as a concise release note: what changed, why it matters…"
          className="rounded-md border border-strong bg-surface px-2.5 py-2 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
      </div>
      <div className="flex items-center gap-2">
        <Button type="submit" disabled={save.isPending || !name.trim() || !prompt.trim()}>
          <Plus size={14} aria-hidden />
          {save.isPending ? "Saving…" : existing ? "Save changes" : "Create preset"}
        </Button>
        {existing && (
          <button
            type="button"
            onClick={onDone}
            className="flex items-center gap-1 text-xs text-fg-muted hover:text-fg cursor-pointer"
          >
            <X size={12} aria-hidden />
            Cancel
          </button>
        )}
        {save.isError && (
          <span className="text-xs text-red-400">{errorMessage(save.error)}</span>
        )}
      </div>
    </form>
  );
}
