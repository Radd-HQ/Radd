import { Lock } from "lucide-react";

/** Amber "Restricted" chip for fields carrying any permission grant (spec 07/36). */
export function RestrictedBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-amber-400/40 bg-amber-500/10 px-1.5 py-px text-[11px] font-medium text-amber-300">
      <Lock size={10} aria-hidden />
      Restricted
    </span>
  );
}
