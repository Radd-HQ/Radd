import { ScopedAccess } from "@radd/plugin-sdk";

export function SpaceAccessPanel({ spaceId, spaceName, canManage }: {
  spaceId: string; spaceName: string; canManage: boolean;
}) {
  return <ScopedAccess scopeId={spaceId} scopeName={spaceName} kind="space" canGrant={canManage} canRevoke={canManage} canRenew={canManage} />;
}
