import { useState } from "react";
import { Globe } from "lucide-react";
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
  transferTo, onTransferTo, noun = "view", existing,
}: {
  serverAccess: ShareLevelValue | typeof SERVER_PRIVATE;
  onServerAccess: (value: ShareLevelValue | typeof SERVER_PRIVATE) => void;
  shares: LocalShare[]; onShares: (next: LocalShare[]) => void;
  canBroadcast: boolean; transferTo?: string; onTransferTo?: (userId: string) => void;
  noun?: "view" | "dashboard";
  existing?: { id: string; draft: SharingDraft; onChange: (value: SharingDraft) => void };
}) {
  const [adding, setAdding] = useState(false);
  const rows = useKeyedRows(shares, onShares);
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
    {existing ? <SharingGrantsEditor resourceType={noun} resourceId={existing.id} draft={existing.draft} onChange={existing.onChange} /> : <>
      {shares.map((share, index) => <div key={rows.keys[index]} className="flex min-w-0 flex-wrap items-center gap-2 text-xs">
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
