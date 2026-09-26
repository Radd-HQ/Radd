import { useQuery } from "@tanstack/react-query";
import { usePermissions } from "@radd/plugin-sdk";
import { pageSpaceSummaryQuery } from "./queries";

/** The wiki's atoms (RADD-791: space-scoped). A page comment needs `comment.write` (RADD-770). */
export const PagePermission = {
  read: "page.read",
  write: "page.write",
  manage: "page.manage",
  commentWrite: "comment.write",
} as const;

/**
 * Space-scoped affordance checks (RADD-814). A space row carries the caller's per-space permission
 * union the way a project row does, so it is asked through the SDK's scope check; "in any space"
 * asks the same of the summary's union. The server still enforces every write.
 */
export function useSpacePermissions() {
  const perms = usePermissions();
  const summary = useQuery(pageSpaceSummaryQuery());
  return {
    space: (space: { permissions?: string[] } | null | undefined, atom: string) =>
      Boolean(space) && perms.project({ permissions: space!.permissions ?? [] }, atom),
    anySpace: (atom: string) => perms.project({ permissions: summary.data?.permissions ?? [] }, atom),
  };
}
