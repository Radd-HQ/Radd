/**
 * How often a node runs: once for the set, or once per item (RADD-918).
 *
 * The control is only rendered when the node type offers a CHOICE — a segmented
 * control with one setting is noise, and `set_state` has never had a coherent
 * "once" reading. That decision comes from the server's `node_arity` table, not
 * from a list here: a default that disagrees with the engine is invisible,
 * because nothing fails to compile.
 *
 * The cost is stated because per-item is where it lands. "Once per item" on a
 * scheduled run over a broad query is the difference between one Slack message
 * and two hundred, and nothing else on the canvas says so.
 */
import { NodeArity, type NodeArityInfo, type NodeArityValue } from "../../lib/types";

interface ArityFieldProps {
  rule: NodeArityInfo;
  value: NodeArityValue;
  /** Which arity the node's other params have already decided, and why.
   *
   * A role recipient ("the reporter") is a property of ONE issue, so running
   * once over a set would resolve nobody. The FORCED option stays selectable and
   * the others lock — locking "whichever is not currently checked" would trap
   * someone on the wrong one. */
  forced?: { value: NodeArityValue; reason: string };
  onChange: (arity: NodeArityValue) => void;
}

const COPY: Record<NodeArityValue, { label: string; cost: string }> = {
  [NodeArity.set]: { label: "Once for all items", cost: "one run" },
  [NodeArity.item]: { label: "Once per item", cost: "one run each" },
};

export function ArityField({ rule, value, forced, onChange }: ArityFieldProps) {
  if (rule.options.length < 2) return null;
  // The forced option is what is CHECKED, not merely what is allowed: the
  // params already decided it, and a control disagreeing with what will be
  // saved is worse than no control.
  const current = forced?.value ?? value;

  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="text-[11px] font-medium uppercase tracking-wide text-fg-secondary">
        Run
      </legend>
      <div className="flex gap-1" role="radiogroup" aria-label="Run">
        {rule.options.map((option) => {
          const active = option === current;
          const locked = Boolean(forced) && !active;
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={locked}
              title={locked ? forced?.reason : undefined}
              onClick={() => onChange(option)}
              className={`flex-1 rounded-[6px] border px-2 py-1.5 text-left text-[11px] ${
                active
                  ? "border-emphasis bg-elevated text-heading"
                  : "border-subtle text-fg-secondary hover:border-strong hover:text-fg"
              } ${locked ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
            >
              <span className="block font-medium">{COPY[option].label}</span>
              <span className="block text-fg-muted">{COPY[option].cost}</span>
            </button>
          );
        })}
      </div>
      <p className="text-[11px] text-fg-muted">
        {forced?.reason ??
          (current === NodeArity.item
            ? "Fires once for every item that reaches it — capped per run, and the dry run shows the real count."
            : "Fires once, however many items reach it. Item tokens are blank unless exactly one arrives; use {{items.keys}}.")}
      </p>
    </fieldset>
  );
}
