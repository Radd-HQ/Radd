import { useState } from "react";
import { Button, Modal } from "@radd/plugin-sdk";
import type { Page } from "../types";

/** Change a page's URL segment (RADD-860), pre-filled from the title. */
export function ChangeUrlDialog({
  page,
  spaceSlug,
  onSave,
  onClose,
}: {
  page: Page;
  spaceSlug: string;
  onSave: (slug: string) => void;
  onClose: () => void;
}) {
  const suggested = page.title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  const [slug, setSlug] = useState(page.slug.startsWith("untitled") ? suggested : page.slug);
  return (
    <Modal title="Change URL" onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-[13px] text-fg-secondary">
          The page moves to the new address immediately; links that used the page id keep
          working, links that used the old slug do not. If another page holds the URL, a
          numbered suffix is added.
        </p>
        <div className="flex items-center gap-1 text-[13px]">
          <span className="text-fg-muted">/pages/{spaceSlug}/</span>
          <input
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
            aria-label="New URL segment"
            autoFocus
            className="h-8 flex-1 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading focus:outline-2 focus:outline-focus"
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => slug.trim() && onSave(slug.trim())} disabled={!slug.trim()}>
            Change URL
          </Button>
        </div>
      </div>
    </Modal>
  );
}
