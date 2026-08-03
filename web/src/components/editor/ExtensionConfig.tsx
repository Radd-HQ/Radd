import { useMemo, useState } from "react";
import { Modal } from "../Modal";
import { Button } from "../Button";
import {
  ExtensionCard,
  lookupPageExtension,
  parseExtensionParams,
} from "../../lib/page-extensions";

/**
 * Configure one `radd:<name>` block (RADD-746).
 *
 * This is the raw-parameters editor, and it stays even once RADD-747 generates
 * a proper form: an extension whose plugin was DISABLED has no schema on the
 * wire any more, and a page that still contains its block must remain editable
 * rather than becoming read-only because the form could not be built.
 */
export function ExtensionConfig({
  name,
  body,
  onClose,
  onSave,
}: {
  name: string;
  /** The fence's payload, verbatim. */
  body: string;
  onClose: () => void;
  onSave: (body: string) => void;
}) {
  const [draft, setDraft] = useState(body);
  const parsed = useMemo(() => parseExtensionParams(draft), [draft]);
  const extension = lookupPageExtension(name);

  return (
    <Modal title={`Configure radd:${name}`} onClose={onClose} wide>
      <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-fg-muted">
        Parameters (JSON)
      </label>
      <textarea
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        spellCheck={false}
        rows={8}
        className="w-full rounded-md border border-strong bg-base px-2.5 py-2 font-mono text-[12px] text-fg outline-none focus-visible:outline-2 focus-visible:outline-focus"
      />
      {!parsed.ok && <p className="mt-1 text-[12px] text-red-400">{parsed.error}</p>}

      <p className="mt-4 mb-1 text-[11px] font-semibold uppercase tracking-wide text-fg-muted">
        Preview
      </p>
      <div className="rounded-md border border-subtle bg-base p-2">
        {!extension ? (
          <p className="text-[13px] text-fg-faint">Nothing is registered for radd:{name}.</p>
        ) : parsed.ok ? (
          extension.render(parsed.params)
        ) : (
          <ExtensionCard>
            <p className="text-[13px] text-fg-faint">Fix the parameters to see a preview.</p>
          </ExtensionCard>
        )}
      </div>

      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button disabled={!parsed.ok} onClick={() => onSave(draft)}>
          Save
        </Button>
      </div>
    </Modal>
  );
}
