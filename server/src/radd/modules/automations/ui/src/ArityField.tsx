/** Once for the set vs once per item — only when the served `node_arity` offers a choice. The cost is
 * stated: per item is one Slack message vs two hundred. */
import { NodeArity, type NodeArityInfo, type NodeArityValue } from "./types";

interface ArityFieldProps {
  rule: NodeArityInfo;
  value: NodeArityValue;
  /** Arity the params already decided (a role recipient ⇒ per item). It stays selected; the others lock. */
  forced?: { value: NodeArityValue; reason: string };
  onChange: (arity: NodeArityValue) => void;
}

const COPY: Record<NodeArityValue, { label: string; cost: string }> = {
  [NodeArity.set]: { label: "Once for all issues", cost: "one run" },
  [NodeArity.item]: { label: "Once per issue", cost: "one run each" },
};

export function ArityField({ rule, value, forced, onChange }: ArityFieldProps) {
  if (rule.options.length < 2) return null;
  // The forced option is what is CHECKED.
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
            ? "Fires once for every issue that reaches it — capped per run, and the dry run shows the real count."
            : "Fires once, however many items reach it. Item tokens are blank unless exactly one arrives; use {{items.keys}}.")}
      </p>
    </fieldset>
  );
}
