import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Plus, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { ApiPath } from "../../lib/constants";
import {
  grantResourcesQuery,
  grantsQuery,
  groupsQuery,
  projectsQuery,
  queryKeys,
  rolesQuery,
  teamsQuery,
  usersQuery,
} from "../../lib/queries";
import {
  GrantSubject,
  type AccessGrant,
  type AccessGrantCreate,
  type GrantSubjectValue,
  type Project,
} from "../../lib/types";
import { Button } from "../Button";
import { Select } from "../Select";
import { ScopePicker } from "./ScopePicker";
import { ExpiryChip } from "./AccessInspector";
import { GroupReachHint } from "./GroupReachHint";
import { SUBJECT_ICON, SubjectPicker, type Subject } from "./SubjectPicker";
import { IconButton } from "../IconButton";
import { ErrorText } from "../ErrorText";

const DEFAULT_ACCESSES = ["read", "write"];
const DEFAULT_SUBJECT_KINDS: GrantSubjectValue[] = [
  GrantSubject.role,
  GrantSubject.team,
  GrantSubject.user,
  GrantSubject.group,
];

/**
 * The one reusable access-grant editor (spec 92): lists a resource's grants
 * (subject → access, scoped) and adds new ones via a subject picker (roles /
 * teams / users) + access + the shared ScopePicker. Works for ANY registered
 * resource (custom fields, builtin fields, views, plugins) — pass its
 * resource_type/id.
 *
 * **It reads the resource's own spec** (RADD-947). `GET /grants/resources`
 * serves the same registry the write path validates against, so the form cannot
 * offer something the server refuses. Before this, `accesses` and `subjectKinds`
 * came from each call site and the project ScopePicker rendered unconditionally
 * — which put a "on <projects>" control on the page-restriction dialog, whose
 * spec sets `project_scoped=False` and whose write path answers "page grants
 * can't be scoped".
 *
 * The props remain as an override for a caller that genuinely knows better, and
 * as the fallback for a resource type the registry does not know.
 */
export function AccessGrantsEditor({
  resourceType,
  resourceId,
  accesses,
  subjectKinds,
  description,
}: {
  resourceType: string;
  resourceId: string;
  /** Override the spec's accesses. Omit — the registry is the better answer. */
  accesses?: string[];
  /** Override the spec's subject kinds. Omit; see above. */
  subjectKinds?: GrantSubjectValue[];
  /** Override for the intro line — resources whose grant semantics read
   * differently (attachments) say so here instead of the field-flavored default. */
  description?: ReactNode;
}) {
  const queryClient = useQueryClient();
  const grants = useQuery(grantsQuery(resourceType, resourceId));
  const roles = useQuery(rolesQuery());
  const teams = useQuery(teamsQuery());
  const users = useQuery({ ...usersQuery, retry: false });
  const groups = useQuery(groupsQuery());
  const projects = useQuery(projectsQuery());
  const resources = useQuery(grantResourcesQuery());

  const spec = resources.data?.find((r) => r.resource_type === resourceType);
  const effectiveAccesses = accesses ?? spec?.accesses ?? DEFAULT_ACCESSES;
  const effectiveSubjectKinds = subjectKinds ?? spec?.subjects ?? DEFAULT_SUBJECT_KINDS;
  // Unknown resource type → keep the pre-947 behaviour rather than silently
  // dropping a control someone may need.
  const projectScoped = spec?.project_scoped ?? true;

  const subjects = useMemo<Subject[]>(() => {
    const kinds = effectiveSubjectKinds;
    const out: Subject[] = [];
    if (kinds.includes(GrantSubject.role))
      out.push(...(roles.data ?? []).map((r) => ({ type: GrantSubject.role, id: r.id, name: r.name })));
    if (kinds.includes(GrantSubject.team))
      out.push(...(teams.data ?? []).map((t) => ({ type: GrantSubject.team, id: t.id, name: t.name })));
    if (kinds.includes(GrantSubject.user))
      out.push(...(users.data ?? []).map((u) => ({ type: GrantSubject.user, id: u.id, name: u.name })));
    if (kinds.includes(GrantSubject.group))
      out.push(...(groups.data ?? []).map((g) => ({ type: GrantSubject.group, id: g.id, name: g.name })));
    return out;
  }, [roles.data, teams.data, users.data, groups.data, effectiveSubjectKinds]);

  const nameOf = (g: AccessGrant) =>
    subjects.find((s) => s.type === g.subject_type && s.id === g.subject_id)?.name ?? "—";
  const projectKey = new Map((projects.data ?? []).map((p) => [p.id, p.key]));

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: [...queryKeys.grants, resourceType, resourceId],
    });
    // A field's `restricted` badge may flip — and an attachment's lock too.
    queryClient.invalidateQueries({ queryKey: queryKeys.fields });
    void invalidateEntities(queryClient, Entity.attachment);
  };

  const revoke = useMutation({
    mutationFn: (id: string) => api.delete(`${ApiPath.grants}/${id}`),
    onSuccess: invalidate,
  });

  const list = grants.data ?? [];

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[11px] text-fg-muted">
        {description ?? (
          <>
            No grants = open: anyone who can read the item sees this, anyone who can edit sets it.
            A <strong>read</strong> grant restricts reading to the listed subjects; a{" "}
            <strong>write</strong> grant restricts editing.{" "}
            {projectScoped && <>Scope each grant global or to projects. </>}
            Managers always pass.
          </>
        )}
      </p>

      {list.length === 0 ? (
        <p className="text-xs text-fg-muted">
          No restriction anywhere — anyone who can see this can read it, and anyone who can
          edit its parent can write it.
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {list.map((grant) => {
            const Icon = SUBJECT_ICON[grant.subject_type];
            return (
              <li key={grant.id} className="flex items-center gap-2 text-[13px]">
                <Icon size={12} className="text-fg-faint" aria-hidden />
                <span className="text-fg">{nameOf(grant)}</span>
                <span
                  className="rounded border border-strong px-1.5 py-px text-[11px] uppercase text-fg-secondary"
                  title={
                    grant.effect === "deny"
                      ? `${grant.access} denied to ${nameOf(grant)}` +
                        (grant.project_id ? ` on ${projectKey.get(grant.project_id) ?? "?"}` : " everywhere")
                      : `${grant.access} restricted to ${nameOf(grant)}` +
                        (grant.project_id
                          ? ` on ${projectKey.get(grant.project_id) ?? "?"} only`
                          : " everywhere")
                  }
                >
                  {grant.access}
                </span>
                {grant.effect === "deny" && (
                  <span className="rounded border border-red-500/40 px-1.5 py-px text-[11px] uppercase text-red-400">
                    deny
                  </span>
                )}
                {grant.expires_at && <ExpiryChip expiresAt={grant.expires_at} />}
                {/* RADD-947: a scope chip on an unscopeable resource says
                    "Global" on every row — a distinction with no alternative. */}
                {projectScoped &&
                  (grant.project_id === null ? (
                    <span className="inline-flex items-center gap-1 text-[11px] text-emerald-300">
                      <Globe size={10} /> Global
                    </span>
                  ) : (
                    <span className="rounded bg-elevated px-1 font-mono text-[11px] text-fg">
                      {projectKey.get(grant.project_id) ?? "?"}
                    </span>
                  ))}
                <IconButton
                  danger
                  onClick={() => revoke.mutate(grant.id)}
                  disabled={revoke.isPending}
                  aria-label="Revoke grant"
                  className="ml-auto"
                >
                  <X size={13} />
                </IconButton>
              </li>
            );
          })}
        </ul>
      )}
      {revoke.isError && <ErrorText error={revoke.error} />}

      <AddGrantRow
        resourceType={resourceType}
        resourceId={resourceId}
        accesses={effectiveAccesses}
        subjects={subjects}
        projects={projects.data ?? []}
        projectScoped={projectScoped}
        onAdded={invalidate}
      />
    </div>
  );
}

function AddGrantRow({
  resourceType,
  resourceId,
  accesses,
  subjects,
  projects,
  projectScoped,
  onAdded,
}: {
  resourceType: string;
  resourceId: string;
  accesses: string[];
  subjects: Subject[];
  projects: Project[];
  /** From the resource's spec (RADD-947). False = the sentence ends at the
   *  access level, and `project_ids` is never sent. */
  projectScoped: boolean;
  onAdded: () => void;
}) {
  const [subject, setSubject] = useState<Subject | null>(null);
  const [access, setAccess] = useState(accesses[0]);
  const [effect, setEffect] = useState<"allow" | "deny">("allow");
  const [expiresAt, setExpiresAt] = useState("");
  const [projectIds, setProjectIds] = useState<string[]>([]);

  const add = useMutation({
    mutationFn: () => {
      const body: AccessGrantCreate = {
        resource_type: resourceType,
        resource_id: resourceId,
        subject_type: subject!.type,
        subject_id: subject!.id,
        access,
        effect,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : undefined,
        project_ids: projectScoped ? projectIds : [],
      };
      return api.post(ApiPath.grants, body);
    },
    onSuccess: () => {
      setSubject(null);
      setProjectIds([]);
      onAdded();
    },
  });

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-subtle/60 pt-3">
      <SubjectPicker subjects={subjects} value={subject} onChange={setSubject} />
      {subject?.type === GrantSubject.group && <GroupReachHint groupId={subject.id} />}

      {/* RADD-847: the row reads as a sentence — subject, MAY/may-not, the
          verb, then "on" the scope. RADD-819: one deny row says "may not" —
          nobody else's access touched. */}
      <Select
        value={effect}
        onChange={(v) => setEffect(v as "allow" | "deny")}
        aria-label="Effect"
        options={[
          { value: "allow", label: "may" },
          { value: "deny", label: "may NOT" },
        ]}
      />

      <Select
        value={access}
        onChange={setAccess}
        aria-label="Access level"
        options={accesses.map((a) => ({ value: a, label: a }))}
      />

      {/* RADD-947: only where the resource actually scopes. A page belongs to a
          space, so "on <projects>" was a control whose only outcome was a 409. */}
      {projectScoped && (
        <>
          <span className="text-xs text-fg-muted">on</span>
          <ScopePicker value={projectIds} onChange={setProjectIds} projects={projects} />
        </>
      )}

      {/* RADD-820: temporary elevation that actually ends. Empty = permanent. */}
      <input
        type="date"
        value={expiresAt}
        onChange={(e) => setExpiresAt(e.target.value)}
        aria-label="Expires (optional)"
        title="Optional expiry — the grant stops applying the moment it passes"
        className="h-8 rounded-md border border-strong bg-surface px-2 text-xs text-fg"
      />

      <Button variant="ghost" disabled={!subject || add.isPending} onClick={() => add.mutate()}>
        <Plus size={13} aria-hidden />
        Add grant
      </Button>
      {add.isError && <span className="text-xs text-red-400">{errorMessage(add.error)}</span>}
    </div>
  );
}
