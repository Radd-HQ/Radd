import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookmarkPlus, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../../lib/api";
import { Entity, invalidateEntities } from "../../../lib/cache";
import { ApiPath, apiCardLayoutPresetPath } from "../../../lib/constants";
import { usePermissions } from "../../../lib/hooks";
import { cardLayoutPresetsQuery } from "../../../lib/queries";
import { Permission, type CardLayout, type CardLayoutPreset } from "../../../lib/types";
import { useConfirm } from "../../ConfirmDialog";

/**
 * The shared preset library inside the card designer (spec 109). Applying a
 * preset COPIES its layout into the draft — a snapshot, so later preset edits
 * never restyle existing boards. Browsing is open to every member; saving and
 * deleting ride the cardpreset.* atoms (admins by default).
 */
export function PresetPicker({
  draft,
  canEdit,
  onApply,
}: {
  draft: CardLayout;
  canEdit: boolean;
  onApply: (layout: CardLayout) => void;
}) {
  const perms = usePermissions();
  const queryClient = useQueryClient();
  const presets = useQuery(cardLayoutPresetsQuery());
  const [confirmNode, confirm] = useConfirm();
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");

  const canCreate = perms.global(Permission.cardPresetCreate);
  const canDelete = perms.global(Permission.cardPresetDelete);

  const createPreset = useMutation({
    mutationFn: (presetName: string) =>
      api.post<CardLayoutPreset>(ApiPath.cardLayoutPresets, { name: presetName, layout: draft }),
    onSuccess: () => {
      invalidateEntities(queryClient, Entity.cardLayoutPreset);
      setNaming(false);
      setName("");
    },
  });
  const deletePreset = useMutation({
    mutationFn: (presetId: string) => api.delete<void>(apiCardLayoutPresetPath(presetId)),
    onSuccess: () => invalidateEntities(queryClient, Entity.cardLayoutPreset),
  });

  const rows = presets.data ?? [];
  if (rows.length === 0 && !canCreate) return null;

  return (
    <div className="min-w-0">
      <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
        Presets
      </p>
      {rows.length > 0 && (
        <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto">
          {rows.map((preset) => (
            <li key={preset.id} className="flex items-center gap-1">
              <button
                type="button"
                disabled={!canEdit}
                onClick={() => onApply(structuredClone(preset.layout))}
                title={
                  canEdit
                    ? "Apply — copies the preset onto this view (later preset edits won't touch it)"
                    : "Only view editors can apply a preset"
                }
                className="min-w-0 flex-1 cursor-pointer truncate rounded-md border border-subtle px-2 py-1 text-left text-xs text-fg-secondary hover:border-strong hover:text-fg disabled:cursor-default disabled:opacity-50"
              >
                {preset.name}
              </button>
              {canDelete && (
                <button
                  type="button"
                  aria-label={`Delete the ${preset.name} preset`}
                  onClick={() => {
                    void confirm({
                      title: "Delete preset?",
                      message: `"${preset.name}" leaves the shared library for everyone. Boards it was applied to keep their layout (applying copies).`,
                      confirmLabel: "Delete",
                      danger: true,
                    }).then((ok) => {
                      if (ok) deletePreset.mutate(preset.id);
                    });
                  }}
                  className="cursor-pointer rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400"
                >
                  <Trash2 size={12} aria-hidden />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canCreate &&
        (naming ? (
          <form
            className="mt-2 flex items-center gap-1.5"
            onSubmit={(event) => {
              event.preventDefault();
              const trimmed = name.trim();
              if (trimmed) createPreset.mutate(trimmed);
            }}
          >
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Preset name…"
              maxLength={100}
              className="w-full rounded-md border border-subtle bg-transparent px-2 py-1 text-xs text-fg outline-none placeholder:text-fg-faint focus:border-strong"
            />
            <button
              type="submit"
              disabled={!name.trim() || createPreset.isPending}
              className="cursor-pointer rounded-md border border-strong px-2 py-1 text-xs text-fg-secondary hover:border-emphasis hover:text-fg disabled:opacity-50"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => setNaming(false)}
              className="cursor-pointer rounded-md px-1.5 py-1 text-xs text-fg-muted hover:text-fg"
            >
              Cancel
            </button>
          </form>
        ) : (
          <button
            type="button"
            onClick={() => setNaming(true)}
            className="mt-2 flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-md border border-dashed border-strong px-2 py-1 text-xs text-fg-muted hover:border-emphasis hover:text-fg"
          >
            <BookmarkPlus size={12} aria-hidden />
            Save current as preset…
          </button>
        ))}
      {(createPreset.isError || deletePreset.isError) && (
        <p className="mt-1.5 text-[11px] text-red-400">
          {errorMessage(createPreset.error ?? deletePreset.error)}
        </p>
      )}
      {confirmNode}
    </div>
  );
}
