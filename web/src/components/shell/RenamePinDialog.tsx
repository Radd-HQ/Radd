import { useState } from "react";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { TextField } from "../TextField";

interface RenamePinDialogProps {
  /** The pinned destination's real name — the fallback when no custom label is set. */
  fallbackName: string;
  /** Current custom label, if any. */
  label: string | undefined;
  onSave: (label: string) => void;
  onClose: () => void;
}

/** Rename a pinned top-bar tab (per-user; the destination itself is untouched). */
export function RenamePinDialog({ fallbackName, label, onSave, onClose }: RenamePinDialogProps) {
  const [value, setValue] = useState(label ?? "");
  return (
    <Modal title="Rename tab" onClose={onClose}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          onSave(value);
          onClose();
        }}
      >
        <TextField
          label="Tab label"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={fallbackName}
          maxLength={60}
          hint={`Only your top bar changes. Leave empty to show the original name — “${fallbackName}”.`}
        />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit">Save</Button>
        </div>
      </form>
    </Modal>
  );
}
