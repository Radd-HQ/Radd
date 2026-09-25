import { useState } from "react";
import { initials } from "../lib/meta";
import { usePersonIndicators } from "./PersonName";

/**
 * User avatar (spec 34): a colored circle with the user's initials, or their
 * chosen emoji. Falls back to a hue derived from the id so unconfigured users
 * still get stable, distinct colors.
 *
 * Status decoration comes from plugin-owned person indicator data.
 */

const SIZES = {
  xs: "size-5 text-[9px]",
  sm: "size-6 text-[10px]",
  md: "size-8 text-xs",
  lg: "size-16 text-xl",
} as const;

/** The status dot per avatar size (presence convention — a dot stays
 * crisp where any glyph would smear). */
const DOT_SIZES = {
  xs: "size-1.5",
  sm: "size-2",
  md: "size-2.5",
  lg: "size-4",
} as const;

/** Stable fallback hue from the user id (djb2 over the uuid). */
function fallbackColor(id: string): string {
  let hash = 5381;
  for (const char of id) hash = (hash * 33 + char.charCodeAt(0)) >>> 0;
  return `hsl(${hash % 360} 45% 38%)`;
}

export interface AvatarUser {
  id: string;
  name: string;
  avatar_color?: string | null;
  avatar_emoji?: string | null;
  /** RADD-1295: an uploaded picture, else the identity provider's (server-decided). */
  avatar_url?: string | null;
}

export function Avatar({
  user,
  size = "sm",
  className = "",
  title,
}: {
  user: AvatarUser;
  size?: keyof typeof SIZES;
  className?: string;
  title?: string;
}) {
  const background = user.avatar_color || fallbackColor(user.id);
  const indicators = usePersonIndicators(user.id);
  const dim = indicators.some(indicator => indicator.dim);
  // A picture that fails to load (an IdP URL that expired, a removed blob)
  // falls back to the colour/emoji rather than a broken-image glyph.
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const picture = user.avatar_url && user.avatar_url !== failedUrl ? user.avatar_url : null;
  // The badge is positioned INSIDE the circle element (no wrapper): a wrapper
  // span stretched with flex parents, which slid the badge to the bottom of
  // whatever row hosted the avatar (the comment thread found this).
  return (
    <span
      title={indicators.length ? `${user.name} — ${indicators.map(i => i.title).join("; ")}` : (title ?? user.name)}
      style={picture || user.avatar_emoji ? undefined : { backgroundColor: background }}
      className={
        `relative flex shrink-0 select-none items-center justify-center rounded-full font-semibold text-white ${SIZES[size]} ` +
        (picture || user.avatar_emoji ? "bg-elevated " : "") +
        className
      }
      data-avatar={picture ? "picture" : user.avatar_emoji ? "emoji" : "initials"}
    >
      {picture ? (
        <img
          src={picture}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          draggable={false}
          onError={() => setFailedUrl(picture)}
          className={"size-full rounded-full object-cover " + (dim ? "opacity-50" : "")}
        />
      ) : (
        <span className={dim ? "opacity-50" : ""}>
          {user.avatar_emoji || initials(user.name)}
        </span>
      )}
      {indicators.length > 0 && (
        <span
          aria-label={indicators.map(i => i.ariaLabel).join(", ")}
          className={`absolute -bottom-px -right-px rounded-full ${{ neutral: "bg-fg-muted", warning: "bg-amber-400", danger: "bg-red-400", success: "bg-green-400" }[indicators[0].tone]} ring-2 ring-base ${DOT_SIZES[size]}`}
        />
      )}
    </span>
  );
}
