import { usePluginData, type StatusIndicator } from "@radd/plugin-sdk";
import { useCurrentUser } from "../lib/hooks";

/** Feature-owned status data; the host has no knowledge of the contributing plugin. */
export function usePersonIndicators(personId: string | undefined) {
  const indicators = usePluginData("personIndicators", {}, useCurrentUser()?.id);
  return indicators.filter(indicator => indicator.personId === personId);
}
export function usePersonStatusSuffixes(): Map<string, string> {
  const indicators = usePluginData("personIndicators", {}, useCurrentUser()?.id);
  const result = new Map<string, string>();
  for (const indicator of indicators) {
    if (indicator.textSuffix) result.set(indicator.personId, `${result.get(indicator.personId) ?? ""} ${indicator.textSuffix}`);
  }
  return result;
}
const STATUS_TONES = {
  neutral: "bg-elevated text-fg-secondary",
  warning: "bg-status-warning/15 text-status-warning-ink",
  danger: "bg-status-danger/15 text-status-danger-ink",
  success: "bg-status-success/15 text-status-success-ink",
};
export function StatusChip({ indicator }: { indicator: StatusIndicator }) {
  return <span aria-label={indicator.ariaLabel} title={indicator.title}
    className={`shrink-0 rounded px-1 py-px text-[10px] font-medium leading-3 ${STATUS_TONES[indicator.tone]}`}>
    {indicator.label}
  </span>;
}

/** The quiet "service" chip an automation identity carries in every picker and
 * byline (RADD-869) — the rendering half of `UserDirectoryEntry.source`. */
function ServiceChip() {
  return (
    <span
      aria-label="Service account"
      className="shrink-0 rounded bg-elevated px-1 py-px text-[10px] font-medium leading-3 text-fg-muted"
    >
      service
    </span>
  );
}

export function PersonName({
  user,
  className = "",
}: {
  user: { id: string; name: string; source?: string };
  className?: string;
}) {
  const indicators = usePersonIndicators(user.id);
  const isService = user.source === "service";
  if (!indicators.length && !isService) return <span className={className}>{user.name}</span>;
  return (
    <span
      className={`inline-flex items-center gap-1.5 ${className}`}
      title={indicators.length ? `${user.name} — ${indicators.map(i => i.title).join("; ")}` : undefined}
    >
      {user.name}
      {isService && <ServiceChip />}
      {indicators.map(indicator => <StatusChip key={indicator.id} indicator={indicator} />)}
    </span>
  );
}
