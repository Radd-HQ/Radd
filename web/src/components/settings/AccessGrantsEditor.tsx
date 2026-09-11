import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, X } from "lucide-react";
import { api } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { ApiPath } from "../../lib/constants";
import { grantResourcesQuery, resourceGrantsPageQuery, RESOURCE_GRANTS_PAGE_SIZE } from "../../lib/queries";
import { useDirectory } from "../../lib/useDirectory";
import type { FieldScopePermission } from "../../lib/queries/field-settings";
import type { GrantSubjectValue } from "../../lib/types";
import { Button } from "../Button";
import { DirectoryPager } from "../DirectoryPager";
import { ErrorText } from "../ErrorText";
import { IconButton } from "../IconButton";
import { Spinner } from "../Spinner";
import { TextField } from "../TextField";
import { ExpiryChip } from "./AccessInspector";
import { AddResourceGrantDialog } from "./AddResourceGrantDialog";
import { SUBJECT_ICON } from "./SubjectPicker";

export interface ResourceGrantScope { id: string | null; label: string }

/** The registry defines the model; management reads page grants and authorized names. */
export function AccessGrantsEditor({ resourceType, resourceId, accesses, subjectKinds, description, scope, projectPermission }: {
  resourceType: string; resourceId: string; accesses?: string[];
  subjectKinds?: GrantSubjectValue[]; description?: ReactNode;
  scope?: ResourceGrantScope; projectPermission?: FieldScopePermission;
}) {
  const queryClient = useQueryClient();
  const resources = useQuery(grantResourcesQuery());
  const directory = useDirectory(`${resourceType}:${resourceId}:${scope === undefined ? "all" : scope.id ?? "global"}`, RESOURCE_GRANTS_PAGE_SIZE,
    (q, page) => resourceGrantsPageQuery(resourceType, resourceId, q, page, scope?.id));
  const [adding, setAdding] = useState(false);
  const spec = resources.data?.find(r => r.resource_type === resourceType);
  useEffect(() => {
    if (!directory.busy && !directory.isError && directory.page > 0 && !directory.rows.length)
      directory.setPage(Math.max(0, Math.ceil(directory.total / directory.pageSize) - 1));
  }, [directory.busy, directory.isError, directory.page, directory.rows.length, directory.total, directory.pageSize, directory.setPage]);
  const invalidate = () => void invalidateEntities(queryClient,
    Entity.accessGrant, Entity.field, Entity.attachment, Entity.page, Entity.view, Entity.dashboard);
  const revoke = useMutation({ mutationFn: (id: string) => api.delete(`${ApiPath.grants}/${id}`), onSuccess: invalidate });
  const effectiveAccesses = accesses ?? spec?.accesses ?? [];
  const effectiveSubjects = subjectKinds ?? spec?.subjects ?? [];
  return <section aria-label="Resource grants" className="flex min-w-0 flex-col gap-3">
    {description && <p className="text-xs text-fg-muted">{description}</p>}
    {resources.isPending ? <Spinner label="Loading resource grants…" /> :
      resources.isError ? <div role="alert" className="space-y-2">
        <ErrorText error={resources.error ?? directory.error} />
        <Button variant="secondary" onClick={() => { void resources.refetch(); void directory.refetch(); }}>Retry resource grants</Button>
      </div> : !spec ? <p role="alert" className="text-sm text-fg-muted">This resource's access model is unavailable.</p> : <>
        {!description && <p className="text-xs text-fg-muted">{spec.default_open && !spec.hierarchical
          ? "Allow grants limit an access level to their subjects; deny grants exclude their subjects. Project scopes and expiry determine where and when a grant applies."
          : "Grants follow this resource's access model. Existing parent and owner permissions still apply."}</p>}
        <TextField type="search" label="Find resource grants" value={directory.filter} onChange={event => directory.setFilter(event.target.value)} placeholder="Subject, project, access or effect…" />
        <div aria-busy={directory.busy}>
          {directory.isPending ? <Spinner label="Loading resource grants…" /> : directory.isError ? <div role="alert" className="space-y-2">
            <ErrorText error={directory.error} />
            <Button variant="secondary" onClick={() => void directory.refetch()}>Retry resource grants</Button>
          </div> : !directory.rows.length ? <p className="text-xs text-fg-muted">
            {directory.q ? "No matching grants." : spec.default_open
              ? "No grants are configured here. Parent permissions and other restrictions still apply."
              : "No grants are configured here. Access follows this resource's owner and sharing settings."}
          </p> : <ul className="flex flex-col gap-2">
            {directory.rows.map(grant => {
              const Icon = SUBJECT_ICON[grant.subject_type];
              return <li key={grant.id} data-grant-id={grant.id} className="flex min-w-0 flex-wrap items-center gap-2 text-xs">
                <Icon size={12} className="shrink-0 text-fg-muted" aria-hidden />
                <span className="min-w-0 flex-1 break-words">{grant.subject_name ?? `Unavailable ${grant.subject_type}`}</span>
                <span className="rounded border border-subtle px-1.5 py-px">{grant.effect === "deny" ? "May not" : "May"} {grant.access}</span>
                {grant.expires_at && (grant.expired
                  ? <span className="text-fg-muted" title={grant.expires_at}>Expired {new Date(grant.expires_at).toLocaleDateString()}</span>
                  : <ExpiryChip expiresAt={grant.expires_at} />)}
                {spec.project_scoped && (grant.project_id === null ?
                  <span className="inline-flex items-center gap-1 text-fg-muted"><Globe size={10} aria-hidden /> Global</span> :
                  <span className="rounded bg-elevated px-1 font-mono">{grant.project_key ?? (scope?.id === grant.project_id ? scope.label : "Unavailable project")}</span>)}
                <IconButton danger aria-label="Revoke grant" disabled={revoke.isPending || directory.busy} onClick={() => revoke.mutate(grant.id)}><X size={13} aria-hidden /></IconButton>
              </li>;
            })}
          </ul>}
        </div>
        {!directory.isError && !directory.isPending && <DirectoryPager {...directory} onPage={directory.setPage} label="resource grants" />}
        <Button variant="secondary" className="w-fit" disabled={!effectiveAccesses.length || !effectiveSubjects.length || directory.isPending || directory.isError} onClick={() => setAdding(true)}>Add grant</Button>
      </>}
    {revoke.isError && <div role="alert"><ErrorText error={revoke.error} /></div>}
    {adding && spec && <AddResourceGrantDialog resourceType={resourceType} resourceId={resourceId}
      accesses={effectiveAccesses} subjectKinds={effectiveSubjects} projectScoped={spec.project_scoped}
      scope={scope} projectPermission={projectPermission}
      onClose={() => setAdding(false)} onAdded={invalidate} />}
  </section>;
}
