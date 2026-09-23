import { useState } from "react";
import { initials } from "../lib/meta";
import { leaveTitle, useOnLeave } from "./PersonName";

/**
 * User avatar (spec 34): a colored circle with the user's initials, or their
 * chosen emoji. Falls back to a hue derived from the id so unconfigured users
 * still get stable, distinct colors.
 *
 * On-leave awareness: ONE cached /leave/current query feeds every
 * avatar on screen — someone away today renders dimmed with a palm badge and
 * an "until" tooltip, on every surface that shows people (assignee, reporter,
 * comments, boards, timesheet) with no per-surface wiring.
 */

const SIZES = {
  xs: "size-5 text-[9px]",
  sm: "size-6 text-[10px]",
  md: "size-8 text-xs",
  lg: "size-16 text-xl",
} as const;

/** The away STATUS DOT per avatar size (presence convention — a dot stays
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
  const onLeave = useOnLeave(user.id);
  // A picture that fails to load (an IdP URL that expired, a removed blob)
  // falls back to the colour/emoji rather than a broken-image glyph.
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const picture = user.avatar_url && user.avatar_url !== failedUrl ? user.avatar_url : null;
  // The badge is positioned INSIDE the circle element (no wrapper): a wrapper
  // span stretched with flex parents, which slid the badge to the bottom of
  // whatever row hosted the avatar (the comment thread found this).
  return (
    <span
      title={onLeave ? leaveTitle(user.name, onLeave) : (title ?? user.name)}
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
          className={"size-full rounded-full object-cover " + (onLeave ? "opacity-50" : "")}
        />
      ) : (
        <span className={onLeave ? "opacity-50" : ""}>
          {user.avatar_emoji || initials(user.name)}
        </span>
      )}
      {onLeave && (
        <span
          aria-label="On leave"
          className={`absolute -bottom-px -right-px rounded-full bg-amber-400 ring-2 ring-base ${DOT_SIZES[size]}`}
        />
      )}
    </span>
  );
}
