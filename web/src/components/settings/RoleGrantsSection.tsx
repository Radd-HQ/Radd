import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Globe, Plus, ShieldCheck, X } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { queryKeys } from "../../lib/queries";
import { GRANTS_PAGE_SIZE, type GrantDirectoryRow, type GrantSubject, subjectGrantsPageQuery } from "../../lib/queries/roles";
import { OptionResource } from "../../lib/queries/options";
import { Button } from "../Button";
import { Choices } from "../DirectoryChoices";
import { DirectoryPager } from "../DirectoryPager";
import { ErrorText } from "../ErrorText";
import { IconButton } from "../IconButton";
import { QueryError } from "../QueryError";
import { Spinner } from "../Spinner";
import { GrantRoleDialog } from "./GrantRoleDialog";
import { formatDate } from "../../lib/dates";

/** Individual mutations preserve off-page grants, including expired rows. */
export function RoleGrantsSection({ subject, canManage }: { subject: GrantSubject; canManage: boolean }) {
  const identity = JSON.stringify(subject);
  const [position, setPosition] = useState({ identity, page: 0 });
  if (position.identity !== identity) setPosition({ identity, page: 0 });
  const page = position.identity === identity ? position.page : 0;
  const setPage = (page: number) => setPosition({ identity, page });
  const queryClient = useQueryClient();
  const grants = useQuery(subjectGrantsPageQuery(subject, page));
  const [granting, setGranting] = useState(false);
  const [editing, setEditing] = useState<GrantDirectoryRow>();
  const total = grants.data?.total ?? 0;
  useEffect(() => {
    if (grants.isSuccess && page > 0 && page * GRANTS_PAGE_SIZE >= total)
      setPosition({ identity, page: Math.max(0, Math.ceil(total / GRANTS_PAGE_SIZE) - 1) });
  }, [grants.isSuccess, total, page, identity]);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.roleGrants });
  const changeRole = useMutation({
    mutationFn: ({ grantId, roleId }: { grantId: string; roleId: string }) => api.patch(`${ApiPath.roleGrants}/${grantId}`, { role_id: roleId }),
    onSuccess: invalidate,
  });
  const revoke = useMutation({ mutationFn: (id: string) => api.delete(`${ApiPath.roleGrants}/${id}`), onSuccess: invalidate });
  return <section aria-label="Role grants">
    <div className="mb-2 flex items-center justify-between">
      <h4 className="text-[11px] font-medium uppercase tracking-wide text-fg-faint">Roles</h4>
      {canManage && <Button variant="ghost" onClick={() => setGranting(true)}><Plus size={13} aria-hidden />Grant role</Button>}
    </div>
    <div aria-busy={grants.isFetching}>
      {grants.isPending ? <Spinner label="Loading role grants…" /> : grants.isError ? <div className="space-y-2">
        <QueryError label="role grants" error={grants.error} /><Button variant="secondary" onClick={() => void grants.refetch()}>Retry role grants</Button>
      </div> : !grants.data.rows.length ? <p className="text-xs text-fg-muted">No role grants.</p> :
        <ul className="flex flex-col gap-2">{grants.data.rows.map(grant => <li key={grant.id} data-grant-id={grant.id} className="flex min-w-0 flex-wrap items-center gap-2 text-[13px]">
          <ShieldCheck size={12} className="shrink-0 text-fg-faint" aria-hidden />
          {canManage ? <Button variant="ghost" className="min-w-0 max-w-full" disabled={changeRole.isPending} aria-label={`Change role ${grant.role_name ?? "unavailable"}`} onClick={() => setEditing(grant)}><span className="truncate">{grant.role_name ?? "Unavailable role"}</span></Button>
            : <span className="min-w-0 truncate">{grant.role_name ?? "Unavailable role"}</span>}
          {grant.project_id !== null ? <span className="max-w-full truncate rounded bg-elevated px-1 font-mono text-xs">{grant.scope_label ?? "Unavailable project"}</span>
            : grant.space_id !== null ? <span className="inline-flex min-w-0 max-w-full items-center gap-1 rounded bg-elevated px-1.5 py-px text-xs"><BookOpen size={10} className="shrink-0" aria-hidden /><span className="truncate">{grant.scope_label ?? "Unavailable wiki space"}</span></span>
              : <span className="inline-flex items-center gap-1 rounded border border-subtle px-1.5 py-px text-xs text-fg-secondary"><Globe size={10} aria-hidden />Global</span>}
          {grant.expires_at && <span className="text-xs text-fg-muted">{Date.parse(grant.expires_at) <= Date.now() ? "Expired" : "Expires"} {formatDate(grant.expires_at)}</span>}
          {canManage && <IconButton danger className="ml-auto" disabled={revoke.isPending} aria-label="Revoke grant" onClick={() => revoke.mutate(grant.id)}><X size={13} aria-hidden /></IconButton>}
        </li>)}</ul>}
    </div>
    <DirectoryPager page={page} pageSize={GRANTS_PAGE_SIZE} total={total} busy={grants.isFetching} onPage={setPage} label="role grants" />
    {revoke.isError && <ErrorText className="mt-1" error={revoke.error} />}
    {changeRole.isError && <ErrorText className="mt-1" error={changeRole.error} />}
    {granting && <GrantRoleDialog subject={subject} onClose={() => setGranting(false)} onGranted={() => void invalidate()} />}
    {editing && <Choices resource={OptionResource.role} selected={editing.role_id} onClose={() => setEditing(undefined)} onSelect={row => {
      changeRole.mutate({ grantId: editing.id, roleId: row.value }); setEditing(undefined);
    }} />}
  </section>;
}
