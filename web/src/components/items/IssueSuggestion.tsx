import { Link, useNavigate } from "@tanstack/react-router";
import { GitMerge } from "lucide-react";
import { useConfirm, type IssueSuggestionProps } from "@radd/plugin-sdk";
import { RoutePath } from "../../lib/constants";
import { useOpenIssueRef } from "../../lib/hooks";
import { useMergeItem } from "../../lib/item-mutations";
import { SimilarHoverCard, useIssuePreview } from "./SimilarHoverCard";

/**
 * One suggested issue as a list row — the SDK's `IssueSuggestion` (RADD-1395), so a plugin that
 * suggests issues draws them exactly as the host would: key + title as a link that opens the PEEK
 * (peek-aware via useOpenIssueRef, so a half-typed form or the issue being read survives the
 * detour), a hover preview so relevance is checkable without opening it (RADD-924), and — where the
 * reader is looking at a duplicate — the RADD-1090 merge. The caller supplies the badge (a score)
 * and the note (why); what they MEAN is the caller's.
 */
export function IssueSuggestion({ itemKey, title, badge, note, mergeFrom, onOpen }: IssueSuggestionProps) {
  const openRef = useOpenIssueRef();
  const preview = useIssuePreview();
  const navigate = useNavigate();
  const mergeItem = useMergeItem();
  const [confirmNode, confirm] = useConfirm();

  return (
    <li {...preview.handlers} className="rounded-md border border-subtle bg-surface/50 px-2.5 py-1.5">
      {preview.anchor && <SimilarHoverCard itemKey={itemKey} anchor={preview.anchor} />}
      <div className="flex items-center gap-2">
        <Link
          to={RoutePath.issue}
          params={{ itemKey }}
          onClick={(event) => {
            if (openRef(itemKey, event)) onOpen?.();
          }}
          className="min-w-0 flex-1 truncate text-[13px] text-fg hover:underline"
        >
          <span className="mr-1.5 font-mono text-[11px] text-fg-muted">{itemKey}</span>
          {title}
        </Link>
        {badge}
        {mergeFrom && (
          <button
            type="button"
            title="Merge this issue into that one — comments, time and links move; this one closes as a duplicate"
            className="shrink-0 cursor-pointer rounded-md border border-strong p-1 text-fg-muted outline-focus hover:border-emphasis hover:text-fg"
            onClick={() => {
              void (async () => {
                const ok = await confirm({
                  title: `Merge into ${itemKey}?`,
                  message:
                    "Comments, attachments, links, watchers and logged time move to " +
                    `${itemKey}; this issue closes as its duplicate. ` +
                    "Worklogs keep their authors.",
                  confirmLabel: "Merge",
                });
                if (!ok) return;
                mergeItem.mutate(
                  { sourceId: mergeFrom, targetKey: itemKey },
                  {
                    onSuccess: (survivor) => {
                      onOpen?.();
                      void navigate({ to: RoutePath.issue, params: { itemKey: survivor.key } });
                    },
                  },
                );
              })();
            }}
          >
            <GitMerge size={13} aria-hidden />
          </button>
        )}
      </div>
      {confirmNode}
      {note && <p className="mt-0.5 text-[11px] text-fg-faint">{note}</p>}
    </li>
  );
}
