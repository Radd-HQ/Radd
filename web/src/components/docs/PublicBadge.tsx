import { Globe } from "lucide-react";

/** The small "Public" chip authed docs surfaces show on public spaces (spec 74). */
export function PublicBadge() {
  return (
    <span
      title="Readable without login at /kb"
      className="inline-flex items-center gap-1 rounded bg-emerald-500/15 px-1.5 py-px text-[10px] font-medium text-emerald-300"
    >
      <Globe size={10} aria-hidden />
      Public
    </span>
  );
}
