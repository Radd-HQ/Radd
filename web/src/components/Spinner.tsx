import { Loader2 } from "lucide-react";

/** Centered loading indicator for route/page-level pending states. */
export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 p-10 text-sm text-fg-muted">
      <Loader2 size={16} className="animate-spin" aria-hidden />
      {label}
    </div>
  );
}
