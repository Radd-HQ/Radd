import {
  Children,
  Fragment,
  isValidElement,
  useId,
  type ChangeEvent,
  type ChangeEventHandler,
  type ReactNode,
} from "react";
import { Select, type SelectOption } from "./Select";

interface SelectFieldProps {
  label: string;
  hint?: string;
  error?: string;
  value?: string | number;
  /** Native-select-shaped handler: only `event.target.value` is populated. */
  onChange?: ChangeEventHandler<HTMLSelectElement>;
  disabled?: boolean;
  title?: string;
  id?: string;
  /**
   * Accessible name for a select with no visible label (a dense grid row, where a
   * label per control would be noise). Required whenever `label` is empty: an
   * empty `<label>` element is an a11y hole AND a stray flex gap, so a blank
   * `label` renders no element at all and leans on this instead.
   */
  ariaLabel?: string;
  className?: string;
  /** `<option>` children (plain, in arrays, or in fragments), as with a native select. */
  children?: ReactNode;
}

/** Plain text of an option's label — the native fallback for a value-less `<option>`. */
function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children);
  return "";
}

/** Translate `<option>` children (arrays/fragments included) into Select options.
 * `<optgroup>` renders as a disabled header row followed by its options — the
 * walker used to SKIP the whole group, which made a grouped select silently
 * empty (the automations trigger dropdown showed "0 events"). */
function optionsFrom(children: ReactNode): SelectOption[] {
  const options: SelectOption[] = [];
  const walk = (nodes: ReactNode) => {
    Children.forEach(nodes, (node) => {
      if (!isValidElement(node)) return;
      if (node.type === Fragment) {
        walk((node.props as { children?: ReactNode }).children);
        return;
      }
      if (node.type === "optgroup") {
        const props = node.props as { label?: string; children?: ReactNode };
        if (props.label) {
          options.push({
            // Disabled = unselectable + skipped by keyboard/type-ahead; the
            // value only needs to never collide with a real option's.
            value: `__optgroup-${options.length}`,
            label: (
              <span className="text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
                {props.label}
              </span>
            ),
            disabled: true,
          });
        }
        walk(props.children);
        return;
      }
      if (node.type !== "option") return;
      const props = node.props as {
        value?: string | number;
        disabled?: boolean;
        title?: string;
        children?: ReactNode;
      };
      options.push({
        value: props.value !== undefined ? String(props.value) : textOf(props.children),
        label: props.children,
        disabled: props.disabled || undefined,
        title: props.title,
      });
    });
  };
  walk(children);
  return options;
}

/** Labeled Select, dense dark styling to match TextField. */
export function SelectField({
  label,
  hint,
  error,
  className = "",
  children,
  value,
  onChange,
  disabled,
  title,
  id,
  ariaLabel,
}: SelectFieldProps) {
  const genId = useId();
  const selectId = id ?? genId;
  const hintId = `${selectId}-hint`;
  const handleChange = (next: string) =>
    onChange?.({
      target: { value: next },
      currentTarget: { value: next },
    } as ChangeEvent<HTMLSelectElement>);
  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label htmlFor={selectId} className="text-xs font-medium text-fg-secondary">
          {label}
        </label>
      )}
      <Select
        id={selectId}
        value={value === undefined || value === null ? "" : String(value)}
        onChange={handleChange}
        options={optionsFrom(children)}
        disabled={disabled}
        invalid={Boolean(error)}
        title={title}
        aria-label={label ? undefined : (ariaLabel ?? title)}
        aria-describedby={hint || error ? hintId : undefined}
        className={className}
      />
      {error ? (
        <p id={hintId} className="text-xs text-red-400">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-xs text-fg-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
