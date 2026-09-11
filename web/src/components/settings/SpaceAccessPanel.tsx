import { ScopedAccessPanel } from "./ScopedAccessPanel";

export function SpaceAccessPanel({ spaceId, spaceName, canManage }: {
  spaceId: string; spaceName: string; canManage: boolean;
}) {
  return <ScopedAccessPanel scopeId={spaceId} scopeName={spaceName} kind="space" canGrant={canManage} canRevoke={canManage} />;
}
