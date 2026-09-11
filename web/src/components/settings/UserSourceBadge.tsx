import { UserSource, type UserSourceValue } from "../../lib/types";

/** Auth-source labels for the user administration surfaces (spec 84). */
export const SOURCE_LABELS: Record<UserSourceValue, string> = {
  [UserSource.local]: "Local",
  [UserSource.ldap]: "AD",
  [UserSource.oidc]: "SSO",
  [UserSource.service]: "Service",
  [UserSource.email]: "Email",
};

const SOURCE_BADGE_CLASSES: Record<UserSourceValue, string> = {
  [UserSource.local]: "border-strong text-fg-secondary",
  [UserSource.ldap]: "border-sky-500/50 text-sky-300",
  [UserSource.oidc]: "border-violet-500/50 text-violet-300",
  [UserSource.service]: "border-strong text-fg-secondary",
  [UserSource.email]: "border-strong text-fg-secondary",
};

export function SourceBadge({ source }: { source: UserSourceValue }) {
  return (
    <span
      className={`rounded border px-1.5 py-px text-[11px] ${SOURCE_BADGE_CLASSES[source] ?? SOURCE_BADGE_CLASSES[UserSource.local]}`}
    >
      {SOURCE_LABELS[source] ?? source}
    </span>
  );
}
