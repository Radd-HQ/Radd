import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Globe, Plus, ShieldCheck, Users, UsersRound, User as UserIcon, X } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { GRANTS_PAGE_SIZE, spaceGrantsPageQuery, projectGrantsPageQuery } from "../../lib/queries/roles";
import { useDirectory } from "../../lib/useDirectory";
import { QueryError } from "../QueryError";
import { Button } from "../Button";
import { IconButton } from "../IconButton";
import { ErrorText } from "../ErrorText";
import { ListSearchInput } from "../ListSearchInput";
import { DirectoryPager } from "../DirectoryPager";
import { GrantScopedRoleDialog } from "./GrantScopedRoleDialog";
import { GrantExpiryButton } from "./GrantExpiryButton";
import { formatDate } from "../../lib/dates";

/** Direct grants in one space. Global grants remain on the global role surface. */
export function ScopedAccessPanel({ scopeId, scopeName, kind, canGrant, canRevoke, canRenew }: {
  scopeId: string; scopeName: string; kind: "space" | "project"; canGrant: boolean; canRevoke: boolean; canRenew: boolean;
}) {
  const queryClient = useQueryClient();
  const grants = useDirectory(`${kind}:${scopeId}`, GRANTS_PAGE_SIZE, (q, page) => kind === "space" ? spaceGrantsPageQuery(scopeId, q, page) : projectGrantsPageQuery(scopeId, q, page));
  const [granting, setGranting] = useState(false);
  const { page, total, isSuccess } = grants;
  useEffect(() => {
    if (isSuccess && page > 0 && page * GRANTS_PAGE_SIZE >= total)
      grants.setPage(Math.max(0, Math.ceil(total / GRANTS_PAGE_SIZE) - 1));
  }, [page, total, isSuccess]);
  const invalidate = () => invalidateEntities(queryClient, Entity.role);
  const revoke = useMutation({
    mutationFn: (grantId: string) => api.delete(`${ApiPath.roleGrants}/${grantId}`),
    onSuccess: invalidate,
  });
  return <section aria-label={kind === "space" ? "Space access" : "Project access"} className="mt-2 rounded-md border border-subtle bg-surface/40 p-3">
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
      <h5 className="text-[11px] font-medium uppercase tracking-wide text-fg-faint">Access</h5>
      {canGrant && <Button variant="ghost" size="sm" onClick={() => setGranting(true)}><Plus size={12} aria-hidden />Grant role</Button>}
    </div>
    <ListSearchInput value={grants.filter} onChange={grants.setFilter} placeholder="Find grants by name…"
      ariaLabel={`Find ${kind} grants`} total={grants.filter.trim() ? undefined : total} matched={total} noun="grants" />
    <div aria-busy={grants.busy} className="mt-3">
      {grants.isPending ? <p role="status" className="text-xs text-fg-muted">Loading {kind} access…</p>
        : grants.isError ? <div className="space-y-2"><QueryError label={`${kind} access`} error={grants.error} /><Button variant="secondary" onClick={() => void grants.refetch()}>Retry access</Button></div>
        : grants.rows.length === 0 ? <p className="text-xs text-fg-muted">{grants.filter.trim() ? "No matching grants." : `No ${kind}-specific grants. Instance-wide roles may still apply.`}</p>
        : <ul className="flex flex-col gap-2">{grants.rows.map(grant => {
          const Icon = grant.team_id ? Users : grant.group_id ? UsersRound : UserIcon;
          const kind = grant.team_id ? "Team" : grant.group_id ? "Group" : "Person";
          return <li key={grant.id} data-grant-id={grant.id} className="flex min-w-0 flex-wrap items-center gap-2 text-[13px]">
            <ShieldCheck size={12} className="shrink-0 text-fg-faint" aria-hidden />
            <span className="min-w-0 break-words text-fg">{grant.role_name ?? "Unavailable role"}</span>
            <span className="inline-flex min-w-0 items-center gap-1 rounded bg-elevated px-1.5 py-px text-[11px] text-fg-secondary">
              <Icon size={10} className="shrink-0" aria-hidden /><span className="min-w-0 break-words">{kind}: {grant.subject_name ?? "Unavailable name"}</span>
            </span>
            {grant.subject_active === false && <span className="text-xs text-fg-muted">Inactive account</span>}
            {grant.expires_at && <span className="text-xs text-fg-muted" title={grant.expires_at}>{grant.expired ? "Expired" : "Expires"} {formatDate(grant.expires_at)}</span>}
            {canRenew && <GrantExpiryButton path={`${ApiPath.roleGrants}/${grant.id}/expiry`} onSaved={invalidate} />}
            {canRevoke && <IconButton danger onClick={() => revoke.mutate(grant.id)} disabled={revoke.isPending} aria-label="Revoke grant" className="ml-auto"><X size={13} aria-hidden /></IconButton>}
          </li>;
        })}</ul>}
    </div>
    <DirectoryPager {...grants} onPage={grants.setPage} label={`${kind} grants`} />
    <p className="mt-2 flex items-start gap-1 text-[11px] text-fg-faint"><Globe size={10} className="mt-0.5 shrink-0" aria-hidden />This list shows direct grants only. Instance-wide roles, team membership and nested directory groups can also provide access. Use the person’s access inspector to review those sources.</p>
    {revoke.isError && <div role="alert"><ErrorText error={revoke.error} /></div>}
    {granting && <GrantScopedRoleDialog scopeId={scopeId} scopeName={scopeName} kind={kind} onClose={() => setGranting(false)} onGranted={invalidate} />}
  </section>;
}
