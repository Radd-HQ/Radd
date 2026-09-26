import { useCallback, useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import type { PluginContribution } from "./plugin";
import { ownedMetaId, Slot, useContributionOwner, useSlot, type SlotIdValue } from "./slots";

/**
 * Contributed MODES — the shared half of `palette-modes.ts` and `query-modes.ts`. A mode is a slot
 * contribution whose `meta` describes it and whose `render` is its GATE: mounted while the surface
 * is open, it calls `useAvailable` and reports. The surface draws the trigger itself, so the gate
 * is what keeps an unavailable, withdrawn or crashing mode from being offered.
 */

/** An icon a mode or an answer row names. The host draws it at its surface's size and colour; any
 *  lucide-react icon fits. */
export type ModeIcon = ComponentType<{ size?: number; className?: string; "aria-hidden"?: boolean }>;

/** What every contributed mode declares. */
export interface ModeSpec {
  /** `<plugin>.<name>` of the registering plugin; another prefix is refused. */
  id: string;
  /** The mode's name where it is offered ("Ask"). */
  label: string;
  /** What it does, in a phrase ("search by meaning"). */
  hint: string;
  icon?: ModeIcon;
  /**
   * A React HOOK — the host calls it from a component of its own, mounted while the surface is
   * open — answering whether the mode may be offered now. It may read queries, preferences,
   * anything a component may. Absent = always.
   */
  useAvailable?: () => boolean;
}

/** A registered, available mode as the host sees it. */
export type ContributedMode<S extends ModeSpec> = Omit<S, "useAvailable"> & {
  plugin: string;
  /** Changes when the plugin registers again: part of any identity derived from the mode. */
  generation: number;
};

type Report = (key: string, available: boolean) => void;

const always = () => true;
const reportKey = (plugin: string | null, id: string) => `${plugin ?? ""}\u0000${id}`;

function ModeGate({ id, useAvailable, report }: { id: string; useAvailable?: () => boolean; report: Report }) {
  const owner = useContributionOwner();
  // Fixed for this instance: a registration that changes it is a new generation, a new mount.
  const probe = useAvailable ?? always;
  const available = probe();
  useEffect(() => {
    const key = reportKey(owner, id);
    report(key, available);
    return () => report(key, false);
  }, [owner, id, available, report]);
  return null;
}

/** The contribution row a mode helper returns: `meta` is the spec without its hook, `render` its gate. */
export function modeContribution<S extends ModeSpec>(slot: SlotIdValue, spec: S, label: string): PluginContribution {
  const { useAvailable, ...meta } = spec;
  return {
    id: `mode:${spec.id}`,
    slot,
    match: spec.id,
    label,
    meta: meta as Readonly<Record<string, unknown>>,
    render: (props: Record<string, unknown>) => (
      <ModeGate id={spec.id} useAvailable={useAvailable} report={props.report as Report} />
    ),
  };
}

const isText = (value: unknown): value is string => typeof value === "string" && value.trim() !== "";

/** The checks every mode's meta passes: its own id, namespaced by its owner, with a name and a hint. */
function isModeMeta(plugin: string, match: string | undefined, meta: Readonly<Record<string, unknown>> | undefined) {
  if (!meta || !ownedMetaId(plugin, match, meta)) return false;
  return isText(meta.label) && isText(meta.hint) && (meta.icon === undefined || typeof meta.icon === "function" || typeof meta.icon === "object");
}

/**
 * The modes contributed to `slot` that are registered, turned on (either toggle scope hides one)
 * and AVAILABLE, in `order`; and the gates the surface must render while `active` — without them
 * no mode is ever available. `accept` checks the slot's own fields (its functions).
 */
export function useContributedModes<S extends ModeSpec>(
  slot: SlotIdValue,
  accept: (meta: Readonly<Record<string, unknown>>) => boolean,
  active: boolean,
): { modes: ContributedMode<S>[]; gates: ReactNode } {
  const entries = useSlot(slot);
  const [available, setAvailable] = useState<ReadonlyMap<string, boolean>>(() => new Map());
  const report = useCallback<Report>((key, ok) => {
    setAvailable((previous) => ((previous.get(key) ?? false) === ok ? previous : new Map(previous).set(key, ok)));
  }, []);
  const modes = useMemo(() => {
    const seen = new Set<string>();
    const out: ContributedMode<S>[] = [];
    for (const entry of entries) {
      const meta = entry.contribution.meta;
      if (!isModeMeta(entry.plugin, entry.contribution.match, meta) || !accept(meta!)) continue;
      const id = meta!.id as string;
      if (seen.has(id) || !available.get(reportKey(entry.plugin, id))) continue;
      seen.add(id);
      out.push({ ...(meta as unknown as Omit<S, "useAvailable">), plugin: entry.plugin, generation: entry.generation });
    }
    return out;
    // `accept` is a module-level check per slot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries, available]);
  const gates = active ? <Slot id={slot} report={report} /> : null;
  return { modes, gates };
}
