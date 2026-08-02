/**
 * The theme tokens as JS `var(--radd-*)` references, for inline styles where a class doesn't fit.
 * Values are CSS `var()` expressions (not hex), so they resolve against the host theme at render —
 * a plugin importing `tokens.accent` never embeds a color literal (spec 94 LOCKED-4).
 */
export const tokens = {
  bg: "var(--radd-bg)",
  panel: "var(--radd-panel)",
  elevated: "var(--radd-elevated)",
  overlay: "var(--radd-overlay)",
  panelHover: "var(--radd-panel-hover)",
  border: "var(--radd-border)",
  borderStrong: "var(--radd-border-strong)",
  heading: "var(--radd-heading)",
  text: "var(--radd-text)",
  textMuted: "var(--radd-text-muted)",
  textFaint: "var(--radd-text-faint)",
  accent: "var(--radd-accent)",
  accentHover: "var(--radd-accent-hover)",
  accentFg: "var(--radd-accent-fg)",
  focus: "var(--radd-focus)",
  danger: "var(--radd-danger)",
  success: "var(--radd-success)",
  warning: "var(--radd-warning)",
  radius: "var(--radd-radius)",
  radiusLg: "var(--radd-radius-lg)",
  fontSans: "var(--radd-font-sans)",
  shadowPop: "var(--radd-shadow-pop)",
  shadowModal: "var(--radd-shadow-modal)",
} as const;

export type TokenName = keyof typeof tokens;
