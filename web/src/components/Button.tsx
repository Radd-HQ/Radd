import type { ButtonHTMLAttributes } from "react";

const ButtonVariant = {
  primary: "primary",
  secondary: "secondary",
  ghost: "ghost",
  danger: "danger",
  dangerGhost: "danger-ghost",
} as const;
type ButtonVariantValue = (typeof ButtonVariant)[keyof typeof ButtonVariant];

const ButtonSize = {
  sm: "sm",
  md: "md",
} as const;
type ButtonSizeValue = (typeof ButtonSize)[keyof typeof ButtonSize];

const baseClasses =
  "inline-flex items-center gap-1.5 rounded-md font-medium " +
  "transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 " +
  "focus-visible:outline-focus disabled:opacity-50 disabled:pointer-events-none " +
  "cursor-pointer select-none";

const variantClasses: Record<ButtonVariantValue, string> = {
  [ButtonVariant.primary]: "bg-accent text-white hover:bg-accent-hover",
  [ButtonVariant.secondary]: "border border-subtle bg-elevated text-fg hover:border-strong",
  [ButtonVariant.ghost]: "text-fg-secondary hover:bg-overlay hover:text-heading",
  [ButtonVariant.danger]: "bg-status-danger/90 text-white hover:bg-status-danger",
  [ButtonVariant.dangerGhost]: "text-status-danger-ink hover:bg-status-danger/10",
};

const sizeClasses: Record<ButtonSizeValue, string> = {
  [ButtonSize.sm]: "h-7 px-2.5 text-xs",
  [ButtonSize.md]: "h-8 px-3 text-[13px]",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariantValue;
  size?: ButtonSizeValue;
}

export function Button({
  variant = ButtonVariant.primary,
  size = ButtonSize.md,
  className = "",
  ...props
}: ButtonProps) {
  return (
    <button
      type="button"
      {...props}
      className={`${baseClasses} ${sizeClasses[size]} ${variantClasses[variant]} ${className}`}
    />
  );
}
