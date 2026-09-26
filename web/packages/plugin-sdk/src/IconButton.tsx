import type { ButtonHTMLAttributes, Ref } from "react";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Required — an icon-only button is unlabeled without it. */
  "aria-label": string;
  /** Destructive affordance: the hover tint goes danger instead of neutral. */
  danger?: boolean;
  /** React 19 ref-as-prop (menu triggers hand one in). */
  ref?: Ref<HTMLButtonElement>;
}

/** The compact icon-only button; `aria-label` is required by the type. `danger` tints the hover for
 *  destructive actions; layout goes in `className`. */
export function IconButton({ danger = false, className = "", ...props }: IconButtonProps) {
  return (
    <button
      type="button"
      {...props}
      className={
        "rounded p-1 text-fg-faint hover:bg-elevated cursor-pointer " +
        "focus-visible:outline-2 focus-visible:outline-focus " +
        "disabled:opacity-50 disabled:pointer-events-none " +
        (danger ? "hover:text-status-danger-ink " : "hover:text-fg ") +
        className
      }
    />
  );
}
