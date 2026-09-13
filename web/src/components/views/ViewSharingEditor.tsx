import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Globe, Earth } from "lucide-react";
import { instanceConfigQuery } from "../../lib/queries/core";
import { OptionResource } from "../../lib/queries/options";
import { useKeyedRows } from "../../lib/keyed-rows";
import { ShareLevel, type ShareLevelValue } from "../../lib/types";
import type { LocalShare, SharingDraft } from "../../lib/sharing-draft";
import { Button } from "../Button";
import { OptionSelect } from "../DirectoryChoices";
import { Select } from "../Select";
import { AddSharingGrantDialog, SHARE_LEVEL_OPTIONS } from "./AddSharingGrantDialog";
import { SharingGrantsEditor } from "./SharingGrantsEditor";

export type { LocalShare } from "../../lib/sharing-draft";
/** Sentinel for private access; never sent as a grant level. */
export const SERVER_PRIVATE = "";

/** Local sharing draft, committed with the containing view/dashboard save. */
export function ViewSharingEditor({ serverAccess, onServerAccess, shares, onShares, canBroadcast,
  transferTo, onTransferTo, noun = "view", existing, worldShareable = false,
}: {
  serverAccess: ShareLevelValue | typeof SERVER_PRIVATE;
  onServerAccess: (value: ShareLevelValue | typeof SERVER_PRIVATE) => void;
  shares: LocalShare[]; onShares: (next: LocalShare[]) => void;
  canBroadcast: boolean; transferTo?: string; onTransferTo?: (userId: string) => void;
  noun?: "view" | "dashboard";
  existing?: { id: string; draft: SharingDraft; onChange: (value: SharingDraft) => void };
  /** Spec 121: offer "Anyone on the web" — only when the view's project is
   *  public or the view spans all projects (rows are scoped by the actor, so
   *  the world only ever sees public issues of public projects). */
  worldShareable?: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const rows = useKeyedRows(shares, onShares);
  // Spec 121: the world is a share SUBJECT (the Anyone principal) — a viewer
  // grant to it, written through the same rows as any person or team. Only
  // offered for NEW views here; an existing view manages the row in its grants
  // table like every other recipient.
  const { data: instance } = useQuery(instanceConfigQuery);
  const anyoneId = instance?.anyone_id ?? null;
  const worldShare = anyoneId ? shares.find(row => row.kind === "user" && row.subjectId === anyoneId) : undefined;
  return <div className="flex min-w-0 flex-col gap-3">
    <p className="text-xs text-fg-secondary">Owners and co-owners can manage sharing and deletion. Editors can change the {noun}.</p>
    <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-fg-secondary">
      <Globe size={13} className="shrink-0 text-fg-faint" aria-hidden />
      Everyone on this server
      <Select aria-label="Server-wide access" value={serverAccess} onChange={level => onServerAccess(level as ShareLevelValue | "")}
        disabled={!canBroadcast && serverAccess === SERVER_PRIVATE}
        title={canBroadcast ? undefined : `Server-wide sharing needs ${noun} management rights in this scope`}
        size="sm" options={[
          { value: SERVER_PRIVATE, label: "no access (specific recipients only)" },
          { value: ShareLevel.viewer, label: "can view" }, { value: ShareLevel.editor, label: "can edit" },
        ]} />
    </div>
    {worldShareable && anyoneId && !existing && <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-fg-secondary">
      <Earth size={13} className="shrink-0 text-fg-faint" aria-hidden />
      Anyone on the web
      <Select aria-label="Public web access" value={worldShare ? ShareLevel.viewer : SERVER_PRIVATE} size="sm"
        disabled={!canBroadcast && !worldShare}
        title={canBroadcast ? "Visible without signing in — shows only public issues of public projects" : `Sharing with the web needs ${noun} management rights in this scope`}
        onChange={level => onShares(level === ShareLevel.viewer
          ? [...shares.filter(row => row !== worldShare), { kind: "user", subjectId: anyoneId, subjectName: "Anyone on the web", level: ShareLevel.viewer }]
          : shares.filter(row => row !== worldShare))}
        options={[{ value: SERVER_PRIVATE, label: "no access" }, { value: ShareLevel.viewer, label: "can view" }]} />
    </div>}
    {existing ? <SharingGrantsEditor resourceType={noun} resourceId={existing.id} draft={existing.draft} onChange={existing.onChange} /> : <>
      {shares.map((share, index) => share === worldShare ? null : <div key={rows.keys[index]} className="flex min-w-0 flex-wrap items-center gap-2 text-xs">
        <span className="min-w-0 flex-1 break-words">{share.subjectName ?? `Selected ${share.kind}`}</span>
        <Select aria-label="Access level" value={share.level} size="sm" options={SHARE_LEVEL_OPTIONS}
          onChange={level => onShares(shares.map((row, i) => i === index ? { ...row, level: level as ShareLevelValue } : row))} />
        <Button size="sm" variant="ghost" onClick={() => rows.removeAt(index)}>Remove share</Button>
      </div>)}
      <Button variant="secondary" className="w-fit" disabled={shares.length >= 50} onClick={() => setAdding(true)}>Add sharing recipient</Button>
      {shares.length >= 50 && <p className="text-xs text-fg-muted">Create with up to 50 recipients, then add more in sharing settings.</p>}
    </>}
    {onTransferTo && <div className="border-t border-subtle pt-3">
      <OptionSelect resource={OptionResource.person} label="Transfer ownership to" value={transferTo ?? ""} onChange={onTransferTo}
        presets={[{ value: "", label: "Keep the current owner", hint: "" }]} />
      {transferTo && <p className="mt-2 text-xs text-fg-muted">On save, the selected person becomes the owner. The previous owner retains editor access.</p>}
    </div>}
    {adding && <AddSharingGrantDialog onClose={() => setAdding(false)} onAdd={share => {
      if (!shares.some(row => row.kind === share.kind && row.subjectId === share.subjectId && row.level === share.level)) rows.add(share);
      setAdding(false);
    }} />}
  </div>;
}
