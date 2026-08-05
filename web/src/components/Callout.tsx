import type { HTMLAttributes, ReactNode } from "react";
import { CircleAlert, CircleCheck, Info, TriangleAlert, type LucideIcon } from "lucide-react";

const CalloutKind = {
  info: "info",
  success: "success",
  warning: "warning",
  danger: "danger",
} as const;
type CalloutKindValue = (typeof CalloutKind)[keyof typeof CalloutKind];

/* Full class strings per kind — Tailwind only compiles classes it can SEE, so
   no template-built names. The `--callout-*` tokens are the computed per-theme
   scale from index.css (ink 4.5:1 on its own fill, border 3:1 on the page). */
const kindClasses: Record<CalloutKindValue, string> = {
  [CalloutKind.info]:
    "border-callout-info-border/60 bg-callout-info-fill text-callout-info-ink",
  [CalloutKind.success]:
    "border-callout-success-border/60 bg-callout-success-fill text-callout-success-ink",
  [CalloutKind.warning]:
    "border-callout-warning-border/60 bg-callout-warning-fill text-callout-warning-ink",
  [CalloutKind.danger]:
    "border-callout-danger-border/60 bg-callout-danger-fill text-callout-danger-ink",
};

const kindIcons: Record<CalloutKindValue, LucideIcon> = {
  [CalloutKind.info]: Info,
  [CalloutKind.success]: CircleCheck,
  [CalloutKind.warning]: TriangleAlert,
  [CalloutKind.danger]: CircleAlert,
};

interface CalloutProps extends HTMLAttributes<HTMLDivElement> {
  kind: CalloutKindValue;
  children: ReactNode;
  /** Leading icon; default per kind, `null` for none. */
  icon?: LucideIcon | null;
  /** Layout/typography overrides (padding, text size, border-dashed). */
  className?: string;
}

/**
 * An inline notice panel over the `--callout-*` token scale (RADD-901). The
 * amber warning box (`border-amber-500/40 bg-amber-500/5 …`) was hand-copied 9
 * times, each on raw shades the light remap only partly covered — this is that
 * panel as a component, in the four callout kinds the editor already renders.
 * Content is `children`; anything beyond text (headings, lists, buttons)
 * simply nests. Layout tweaks ride `className`.
 */
export function Callout({ kind, children, icon, className = "", ...rest }: CalloutProps) {
  const Icon = icon === null ? null : (icon ?? kindIcons[kind]);
  return (
    <div
      {...rest}
      className={`flex items-start gap-2 rounded-md border p-2.5 text-xs ${kindClasses[kind]} ${className}`}
    >
      {Icon && <Icon size={14} className="mt-px shrink-0" aria-hidden />}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
