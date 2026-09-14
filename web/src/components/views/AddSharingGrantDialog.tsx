import { useState } from "react";
import type { LocalShare } from "../../lib/sharing-draft";
import { OptionResource, type DirectoryOption } from "../../lib/queries/options";
import { ShareLevel, type ShareLevelValue } from "../../lib/types";
import { Button } from "../Button";
import { Choices } from "../DirectoryChoices";
import { Modal } from "../Modal";
import { Select } from "../Select";
import { GroupReachHint } from "../settings/GroupReachHint";

export const SHARE_LEVEL_OPTIONS = [
  { value: ShareLevel.viewer, label: "can view" },
  { value: ShareLevel.editor, label: "can edit" },
  { value: ShareLevel.owner, label: "co-owner" },
];
const resources = { user: OptionResource.person, team: OptionResource.teamReference, group: OptionResource.group };

export function AddSharingGrantDialog({ onAdd, onClose }: { onAdd: (share: LocalShare) => void; onClose: () => void }) {
  const [kind, setKind] = useState<LocalShare["kind"]>("user");
  const [subject, setSubject] = useState<DirectoryOption>();
  const [level, setLevel] = useState<ShareLevelValue>(ShareLevel.viewer);
  const [choosing, setChoosing] = useState(false);
  return <Modal title="Share with…" onClose={onClose}>
    <div className="flex flex-col gap-3">
      <Select aria-label="Share with a person, team or group" value={kind} onChange={value => { setKind(value as LocalShare["kind"]); setSubject(undefined); }}
        options={[{ value: "user", label: "Person" }, { value: "team", label: "Team" }, { value: "group", label: "Directory group" }]} />
      <Button variant="secondary" aria-haspopup="dialog" onClick={() => setChoosing(true)}>{subject?.label ?? "Choose a person, team or group…"}</Button>
      {kind === "group" && subject && <GroupReachHint groupId={subject.value} />}
      <Select aria-label="Access level" value={level} onChange={value => setLevel(value as ShareLevelValue)} options={SHARE_LEVEL_OPTIONS} />
      <p className="text-xs text-fg-muted">They get access when you save.</p>
      <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button disabled={!subject} onClick={() => { if (subject) onAdd({ draftId: crypto.randomUUID(), kind, subjectId: subject.value, subjectName: subject.label, level }); }}>Add</Button></div>
    </div>
    {choosing && <Choices resource={resources[kind]} selected={subject?.value} onClose={() => setChoosing(false)}
      onSelect={row => { setSubject(row); setChoosing(false); }} />}
  </Modal>;
}
