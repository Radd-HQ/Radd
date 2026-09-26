import { useProvided, type ModalProps, type ButtonVariantValue } from "./host-registry";
import {
  useId,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

/**
 * Shared UI primitives (spec 94 LOCKED-4). Each applies a stable `.radd-*` class built from theme
 * tokens, so a plugin gets host-consistent, theme-aware controls with zero styling code and no
 * hardcoded color. A remote imports these from `@radd/plugin-sdk` (a federation singleton).
 */

export const ButtonVariant = { primary: "primary", secondary: "secondary", ghost: "ghost", danger: "danger", dangerGhost: "danger-ghost" } as const;

export function Button({
  variant = "primary",
  small = false,
  size,
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariantValue; small?: boolean; size?: "sm" | "md" }) {
  const { Button: Host } = useProvided();
  if (Host) return <Host variant={variant} size={size ?? (small ? "sm" : "md")} className={className} type={type} {...props} />;
  const cls = ["radd-btn", `radd-btn--${variant}`, small ? "radd-btn--sm" : "", className]
    .filter(Boolean)
    .join(" ");
  return <button type={type} className={cls} {...props} />;
}

export function TextField({
  label,
  hint,
  error,
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: string; error?: string }) {
  const { TextField: Host } = useProvided();
  const id = useId();
  const descId = `${id}-desc`;
  if (Host) return <Host label={label} hint={hint} error={error} className={className} {...props} />;
  return (
    <div className="radd-field">
      {label && (
        <label htmlFor={id} className="radd-field__label">
          {label}
        </label>
      )}
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={hint || error ? descId : undefined}
        className={`radd-input ${className}`}
        {...props}
      />
      {error ? (
        <p id={descId} className="radd-field__error">
          {error}
        </p>
      ) : hint ? (
        <p id={descId} className="radd-field__hint">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function TextArea({
  label,
  hint,
  error,
  className = "",
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label?: string;
  hint?: string;
  error?: string;
}) {
  const id = useId();
  const descId = `${id}-desc`;
  return (
    <div className="radd-field">
      {label && (
        <label htmlFor={id} className="radd-field__label">
          {label}
        </label>
      )}
      <textarea
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={hint || error ? descId : undefined}
        className={`radd-textarea ${className}`}
        {...props}
      />
      {error ? (
        <p id={descId} className="radd-field__error">
          {error}
        </p>
      ) : hint ? (
        <p id={descId} className="radd-field__hint">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function Select({
  label,
  className = "",
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  const id = useId();
  return (
    <div className="radd-field">
      {label && (
        <label htmlFor={id} className="radd-field__label">
          {label}
        </label>
      )}
      <select id={id} className={`radd-select ${className}`} {...props}>
        {children}
      </select>
    </div>
  );
}

export function Chip({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <span className={`radd-chip ${className}`}>{children}</span>;
}

export function Card({
  title,
  children,
  className = "",
}: {
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`radd-card ${className}`}>
      {title && <div className="radd-card__title">{title}</div>}
      {children}
    </div>
  );
}

/** A loading indicator; `label` says what is loading, visibly (RADD-1376 — the pickers' "Loading
 * projects…" had gone silent when they moved onto this). */
export function Spinner({ className = "", label }: { className?: string; label?: string }) {
  if (!label) return <span className={`radd-spinner ${className}`} role="status" aria-label="Loading" />;
  return (
    <span role="status" className="inline-flex items-center gap-2 py-2 text-xs text-fg-muted">
      <span className={`radd-spinner ${className}`} aria-hidden />
      {label}
    </span>
  );
}

export function EmptyState({ children, icon: Icon, message, action }: {
  children?: ReactNode;
  icon?: import("react").ComponentType<{size?: number; className?: string; "aria-hidden"?: boolean}>;
  message?: string;
  action?: ReactNode;
}) {
  if (!Icon && message === undefined && action === undefined) return <div className="radd-empty">{children}</div>;
  return <div className="flex flex-col items-center gap-3 rounded-lg border border-subtle py-14 text-fg-muted">
    {Icon && <Icon size={24} aria-hidden className="text-fg-faint" />}
    {message !== undefined && <p className="text-sm">{message}</p>}{children}{action}
  </div>;
}

export interface AvatarUser {
  id: string;
  name: string;
  avatar_color?: string | null;
  avatar_emoji?: string | null;
  avatar_url?: string | null;
}

const AVATAR_PX: Record<string, number> = { xs: 20, sm: 24, md: 32, lg: 64 };

function fallbackHue(id: string): string {
  let hash = 5381;
  for (const char of id) hash = (hash * 33 + char.charCodeAt(0)) >>> 0;
  return `hsl(${hash % 360} 45% 38%)`;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("") || "?";
}

/** A user avatar: colored initials circle or the user's chosen emoji. Theme-safe (no hardcoded hue
 *  in a plugin — the fallback is derived from the id here in the SDK). */
export function Avatar({
  user,
  size = "sm",
  title,
  className,
}: {
  user: AvatarUser;
  size?: "xs" | "sm" | "md" | "lg";
  title?: string;
  className?: string;
}) {
  const { Avatar: Host } = useProvided();
  if (Host) return <Host user={user} size={size} title={title} className={className} />;
  const px = AVATAR_PX[size] ?? 24;
  const background = user.avatar_emoji
    ? "var(--radd-panel-hover)"
    : user.avatar_color || fallbackHue(user.id);
  return (
    <span
      title={title ?? user.name}
      className={className}
      style={{
        display: "inline-flex",
        flexShrink: 0,
        alignItems: "center",
        justifyContent: "center",
        userSelect: "none",
        borderRadius: "9999px",
        fontWeight: 600,
        color: "var(--radd-accent-fg)",
        width: px,
        height: px,
        fontSize: Math.round(px * 0.42),
        background,
      }}
    >
      {user.avatar_emoji || initials(user.name)}
    </span>
  );
}

export function Modal(props: ModalProps) {
  const { Modal: Host } = useProvided();
  if (Host) return <Host {...props} />;
  const { onClose, children } = props;
  return (
    <div
      className="radd-modal__backdrop"
      onClick={onClose}
      role="presentation"
    >
      <div className="radd-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal>
        {children}
      </div>
    </div>
  );
}
