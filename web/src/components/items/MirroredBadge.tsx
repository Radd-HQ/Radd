import { GitMerge } from "lucide-react";
import { VcsProvider } from "../../lib/types";

/** Human name of the host a worklog was mirrored from (RADD-1258). */
export function sourceLabel(source: string): string {
  switch (source) {
    case VcsProvider.gitlab:
      return "GitLab";
    case VcsProvider.github:
      return "GitHub";
    case VcsProvider.forgejo:
      return "Forgejo";
    default:
      return source || "the source";
  }
}

/**
 * The chip on a worklog that was logged on a merge/pull request and mirrored
 * here — the one signal that explains why the row cannot be edited in Radd.
 */
export function MirroredBadge({ source }: { source: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded bg-elevated px-1.5 py-px text-[11px] text-fg-secondary"
      title={`Mirrored from time logged on ${sourceLabel(source)}. Edit it there.`}
    >
      <GitMerge size={10} aria-hidden />
      from {sourceLabel(source)}
    </span>
  );
}
