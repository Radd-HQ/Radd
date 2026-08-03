import { iconFor } from "../../lib/icons";

/** Pick black or white text for legibility on a given hex background. */
function textOn(hex: string): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return "#fff";
  const n = parseInt(m[1], 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  // Rec. 601 luma — light chips get dark text, dark chips get white.
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#18181b" : "#fff";
}

/**
 * A compact colored chip (OtherTracker style): a small rounded box in the value's
 * color showing a lucide icon or the first letter of the name. Used for issue
 * types on cards, list rows, and the issue rail.
 */
export function ValueChip({
  label,
  color,
  icon,
  size = 16,
}: {
  label: string;
  color: string;
  icon?: string | null;
  size?: number;
}) {
  // `iconFor`, not `iconOrFallback`: a chip with no icon falls back to the
  // value's first LETTER, which reads better in 16px than a placeholder glyph.
  const Icon = iconFor(icon);
  return (
    <span
      title={label}
      aria-label={label}
      className="inline-flex shrink-0 items-center justify-center rounded font-semibold"
      style={{
        width: size,
        height: size,
        backgroundColor: color,
        color: textOn(color),
        fontSize: Math.round(size * 0.6),
        lineHeight: 1,
      }}
    >
      {Icon ? (
        <Icon size={Math.round(size * 0.62)} aria-hidden />
      ) : (
        (label[0] ?? "?").toUpperCase()
      )}
    </span>
  );
}
