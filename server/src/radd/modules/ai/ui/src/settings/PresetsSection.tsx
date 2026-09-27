import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Pencil, Plus, Trash2, WandSparkles } from "lucide-react";
import { api, errorMessage, Button, EmptyState, ErrorText, IconButton, QueryError, Switch, TableSkeleton, TextArea,
  TextField, useConfirm } from "@radd/plugin-sdk";
import { useAiPresets, useInvalidateAi } from "./queries";
import { AiEntity, AiPath, sectionHeadClasses, type AiPreset } from "./types";

/** The editor preset library: enabled presets appear by name in every editor AI menu; the prompt
 *  text never leaves the server. */
export function PresetsSection() {
  const presets = useAiPresets();
  const invalidate = useInvalidateAi();
  const [editing, setEditing] = useState<string | null>(null);

  const remove = useMutation({
    mutationFn: (presetId: string) => api.delete<void>(AiPath.preset(presetId)),
    onSettled: () => invalidate(AiEntity.preset),
  });
  const toggle = useMutation({
    mutationFn: (preset: AiPreset) => api.patch<AiPreset>(AiPath.preset(preset.id), { enabled: !preset.enabled }),
    onSettled: () => invalidate(AiEntity.preset),
  });
  // RADD-1463: a delete is irreversible (the prompt text lives only here), so it asks first.
  const [confirmDialog, confirm] = useConfirm();
  const removePreset = async (preset: AiPreset) => {
    const ok = await confirm({
      title: `Delete ${preset.name}?`,
      message: "The preset leaves every editor's AI menu and its prompt is not kept.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) remove.mutate(preset.id);
  };

  const list = presets.data ?? [];

  return (
    <section data-ai-presets>
      <h2 className={sectionHeadClasses}>Editor presets</h2>
      <p className="mb-3 text-xs text-fg-muted">
        Named prompts offered as actions in every user's editor AI menu, alongside the built-ins. The prompt runs
        server-side against the selection — users see only the name.
      </p>
      {presets.isPending ? (
        <TableSkeleton rows={2} />
      ) : presets.isError ? (
        <QueryError label="AI presets" error={presets.error} />
      ) : (
        <>
          {list.length === 0 ? (
            <EmptyState icon={WandSparkles} message="No presets yet — try one like “Make it release-note ready”." />
          ) : (
            <ul className="rounded-lg border border-subtle">
              {list.map((preset) => (
                <li key={preset.id} data-ai-preset={preset.name} className="border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
                  <div className="flex items-center gap-2">
                    <Switch checked={preset.enabled} onChange={() => toggle.mutate(preset)} disabled={toggle.isPending}
                      label={`Show ${preset.name} in the editor AI menu`} hideLabel />
                    <span className={"flex-1 text-[13px] font-medium " + (preset.enabled ? "text-heading" : "text-fg-faint")}>
                      {preset.name}
                    </span>
                    <IconButton aria-label={`Edit ${preset.name}`}
                      onClick={() => setEditing(editing === preset.id ? null : preset.id)}>
                      <Pencil size={13} aria-hidden />
                    </IconButton>
                    <IconButton danger aria-label={`Delete ${preset.name}`} onClick={() => void removePreset(preset)}>
                      <Trash2 size={13} aria-hidden />
                    </IconButton>
                  </div>
                  <p className="mt-0.5 line-clamp-2 whitespace-pre-wrap text-xs text-fg-muted">{preset.prompt}</p>
                  {editing === preset.id && <PresetForm existing={preset} onDone={() => setEditing(null)} />}
                </li>
              ))}
            </ul>
          )}
          <PresetForm nextPosition={list.length} />
        </>
      )}
      {remove.isError && <ErrorText className="mt-2" error={remove.error} />}
      {toggle.isError && <ErrorText className="mt-2" error={toggle.error} />}
      {confirmDialog}
    </section>
  );
}

function PresetForm({ existing, nextPosition = 0, onDone }: {
  existing?: AiPreset;
  nextPosition?: number;
  onDone?: () => void;
}) {
  const invalidate = useInvalidateAi();
  const [name, setName] = useState(existing?.name ?? "");
  const [prompt, setPrompt] = useState(existing?.prompt ?? "");

  const save = useMutation({
    mutationFn: () =>
      existing
        ? api.patch<AiPreset>(AiPath.preset(existing.id), { name, prompt })
        : api.post<AiPreset>(AiPath.presets, { name, prompt, enabled: true, position: nextPosition }),
    onSuccess: () => {
      if (!existing) {
        setName("");
        setPrompt("");
      }
      onDone?.();
    },
    onSettled: () => invalidate(AiEntity.preset),
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim() && prompt.trim()) save.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="mt-4 flex flex-col gap-3" data-ai-preset-form={existing ? "edit" : "new"}>
      <TextField label={existing ? "Name" : "New preset name"} value={name} onChange={(event) => setName(event.target.value)}
        placeholder="Make it release-note ready" maxLength={200} />
      <TextArea label="Prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={3}
        placeholder="Rewrite the selection as a concise release note: what changed, why it matters…" />
      <div className="flex items-center gap-2">
        <Button type="submit" disabled={save.isPending || !name.trim() || !prompt.trim()}>
          <Plus size={14} aria-hidden />
          {save.isPending ? "Saving…" : existing ? "Save changes" : "Create preset"}
        </Button>
        {existing && <Button variant="ghost" onClick={onDone}>Cancel</Button>}
        {save.isError && <span className="text-xs text-status-danger-ink">{errorMessage(save.error)}</span>}
      </div>
    </form>
  );
}
