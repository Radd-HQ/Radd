import { CheckCircle2, MinusCircle } from "lucide-react";

/** One read-only on/off row of the directory's deploy status. */
export function StatusRow({ label, on }: { label: string; on: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-subtle px-3 py-2" data-directory-status={label}>
      <span className="truncate text-xs text-fg">{label}</span>
      <span className={`inline-flex shrink-0 items-center gap-1 text-[11px] ${on ? "text-status-success-ink" : "text-fg-faint"}`}>
        {on ? <CheckCircle2 size={12} aria-hidden /> : <MinusCircle size={12} aria-hidden />}
        {on ? "On" : "Off"}
      </span>
    </div>
  );
}
