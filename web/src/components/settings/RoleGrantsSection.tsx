import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Globe, Plus, ShieldCheck, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import {
  pageSpacesQuery,
  projectsQuery,
  queryKeys,
  roleGrantsQuery,
  rolesQuery,
} from "../../lib/queries";
import type { RoleGrantCreate } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { SelectField } from "../SelectField";
import { TokenMultiSelect } from "../TokenMultiSelect";
import { ScopePicker } from "./ScopePicker";

type Subject = { teamId: string } | { userId: string };

/**
 * Role grants held by a team or user (spec 91) — the unified, scopeable grant
 * surface. Lists each granted role and its scope (Global or specific projects),
 * with a Grant Role dialog that picks a role + scope. Distinct from project
 * membership: this grants a role WITHOUT making the subject a project member.
 */
export function RoleGrantsSection({
  subject,
  canManage,
}: {
  subject: Subject;
  canManage: boolean;
}) {
  const teamId = "teamId" in subject ? subject.teamId : undefined;
  const userId = "userId" in subject ? subject.userId : undefined;
  const queryClient = useQueryClient();
  const grants = useQuery(roleGrantsQuery({ teamId, userId }));
  const roles = useQuery(rolesQuery());
  const projects = useQuery(projectsQuery());
  const spaces = useQuery(pageSpacesQuery());
  const [granting, setGranting] = useState(false);

  const roleName = new Map((roles.data ?? []).map((r) => [r.id, r.name]));
  const projectKey = new Map((projects.data ?? []).map((p) => [p.id, p.key]));
  const spaceName = new Map((spaces.data ?? []).map((s) => [s.id, s.name]));

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.roleGrants });

  const revoke = useMutation({
    mutationFn: (grantId: string) => api.delete(`${ApiPath.roleGrants}/${grantId}`),
    onSuccess: invalidate,
  });

  const list = grants.data ?? [];

  return (
    <section aria-label="Role grants">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-[11px] font-medium uppercase tracking-wide text-fg-faint">Roles</h4>
        {canManage && (
          <Button variant="ghost" onClick={() => setGranting(true)}>
            <Plus size={13} aria-hidden />
            Grant role
          </Button>
        )}
      </div>

      {list.length === 0 ? (
        <p className="text-xs text-fg-muted">No role grants.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {list.map((grant) => (
            <li key={grant.id} className="flex items-center gap-2 text-[13px]">
              <ShieldCheck size={12} className="text-fg-faint" aria-hidden />
              <span className="text-fg">{roleName.get(grant.role_id) ?? "role"}</span>
              {/* Three scopes, three chips (RADD-791). A space grant used to fall
                  through the project branch and render "Global", which claimed
                  the opposite of what the row actually granted. */}
              {grant.project_id !== null ? (
                <span className="rounded bg-elevated px-1 font-mono text-[11px] text-fg">
                  {projectKey.get(grant.project_id) ?? "?"}
                </span>
              ) : grant.space_id !== null ? (
                <span className="inline-flex items-center gap-1 rounded bg-elevated px-1.5 py-px text-[11px] text-fg">
                  <BookOpen size={10} aria-hidden />
                  {spaceName.get(grant.space_id) ?? "?"}
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 rounded border border-emerald-500/30 px-1.5 py-px text-[11px] text-emerald-300">
                  <Globe size={10} /> Global
                </span>
              )}
              {canManage && (
                <button
                  type="button"
                  onClick={() => revoke.mutate(grant.id)}
                  disabled={revoke.isPending}
                  aria-label="Revoke grant"
                  className="ml-auto rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer disabled:opacity-50"
                >
                  <X size={13} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {revoke.isError && <p className="mt-1 text-xs text-red-400">{errorMessage(revoke.error)}</p>}

      {granting && (
        <GrantRoleDialog
          subject={subject}
          onClose={() => setGranting(false)}
          onGranted={invalidate}
        />
      )}
    </section>
  );
}

function GrantRoleDialog({
  subject,
  onClose,
  onGranted,
}: {
  subject: Subject;
  onClose: () => void;
  onGranted: () => void;
}) {
  const roles = useQuery(rolesQuery());
  const projects = useQuery(projectsQuery());
  const spaces = useQuery(pageSpacesQuery());
  const [roleId, setRoleId] = useState("");
  const [projectIds, setProjectIds] = useState<string[]>([]);
  const [spaceIds, setSpaceIds] = useState<string[]>([]);

  const grant = useMutation({
    mutationFn: () => {
      const body: RoleGrantCreate = {
        role_id: roleId,
        project_ids: projectIds,
        space_ids: spaceIds,
        ...("teamId" in subject ? { team_id: subject.teamId } : { user_id: subject.userId }),
      };
      return api.post(ApiPath.roleGrants, body);
    },
    onSuccess: () => {
      onGranted();
      onClose();
    },
  });

  return (
    <Modal title="Grant role" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          grant.mutate();
        }}
        className="flex flex-col gap-4"
      >
        <SelectField label="Role" value={roleId} onChange={(e) => setRoleId(e.target.value)}>
          <option value="">Choose a role…</option>
          {(roles.data ?? []).map((role) => (
            <option key={role.id} value={role.id}>
              {role.name}
            </option>
          ))}
        </SelectField>

        {/* One dialog, every scope (RADD-791). Naming both a project and a space
            is fine and means what it looks like: one grant per id, each carrying
            its own scope. Leaving both empty is the instance-wide grant. */}
        <div>
          <p className="mb-1.5 text-xs font-medium text-fg-secondary">Projects</p>
          <ScopePicker value={projectIds} onChange={setProjectIds} projects={projects.data ?? []} />
        </div>

        <div>
          <p className="mb-1.5 text-xs font-medium text-fg-secondary">Wiki spaces</p>
          <div className="min-w-44 max-w-72">
            <TokenMultiSelect
              value={spaceIds}
              onChange={setSpaceIds}
              options={(spaces.data ?? []).map((space) => ({
                value: space.id,
                label: space.name,
                hint: space.slug,
              }))}
              placeholder="No space scope"
              ariaLabel="Wiki space scope"
            />
          </div>
          <p className="mt-1.5 text-[11px] text-fg-faint">
            Leave both empty to grant the role everywhere; name projects or spaces to
            grant it only there.
          </p>
        </div>

        {grant.isError && <p className="text-xs text-red-400">{errorMessage(grant.error)}</p>}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!roleId || grant.isPending}>
            {grant.isPending ? "Granting…" : "Grant"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
