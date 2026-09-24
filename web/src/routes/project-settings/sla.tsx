import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Pencil, Timer, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import { apiSlaPolicyPath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { usePermissions } from "../../lib/hooks";
import { PRIORITY_META } from "../../lib/meta";
import { issueTypesQuery, slaPoliciesQuery, statesQuery } from "../../lib/queries";
import { Permission, SettingScope, type SlaPolicy } from "../../lib/types";
import { EmptyState } from "../../components/EmptyState";
import { TableSkeleton } from "../../components/TableSkeleton";
import { ScopedSettingsEditor } from "../../components/settings/ScopedSettingsEditor";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { SlaPolicyForm, minutesLabel, windowLabel } from "../../components/settings/SlaPolicyForm";
import { metRuleSummary } from "../../components/settings/SlaMetOnField";
import { QueryError } from "../../components/QueryError";

/** SLA policies for one project (specs 30/63; project-level since spec 67):
 * targets, priority tiers, business hours, and first-match ordering (up/down,
 * same idiom as the config editors). Editing stays gated on the global-scope
 * `sla.manage` permission, same as the old global-settings page. */
export function ProjectSlaSettingsPage({ projectId }: { projectId?: string }) {
  const perms = usePermissions();
  const canManage = perms.global(Permission.slaUpdate);
  const policies = useQuery({
    ...slaPoliciesQuery(projectId ?? ""),
    enabled: Boolean(projectId),
  });
  const issueTypes = useQuery({
    ...issueTypesQuery(projectId ?? ""),
    enabled: Boolean(projectId),
  });
  const typeName = new Map((issueTypes.data ?? []).map((t) => [t.id, t.name]));
  // RADD-1299: state names for the "met on leaving Triage" summaries.
  const states = useQuery({ ...statesQuery(projectId ?? ""), enabled: Boolean(projectId) });
  const stateName = new Map((states.data ?? []).map((state) => [state.id, state.name]));
  const names = (ids: string[]) => ids.map((id) => stateName.get(id) ?? "?");
  const queryClient = useQueryClient();
  const invalidate = () => invalidateEntities(queryClient, Entity.slaPolicy);
  // RADD-1300: the one policy being edited in place (null = none).
  const [editingId, setEditingId] = useState<string | null>(null);

  const remove = useMutation({
    mutationFn: (policyId: string) => api.delete<void>(apiSlaPolicyPath(policyId)),
    onSettled: invalidate,
  });
  const toggle = useMutation({
    mutationFn: (policy: SlaPolicy) =>
      api.patch<SlaPolicy>(apiSlaPolicyPath(policy.id), { enabled: !policy.enabled }),
    onSettled: invalidate,
  });

  // Server order IS the first-match order (position, created_at). Reorder =
  // renumber to list indices with the two neighbours swapped (up/down idiom,
  // like the issue-type editor — renumbering also heals legacy position ties).
  const list = policies.data ?? [];
  const move = async (index: number, direction: -1 | 1) => {
    if (!list[index] || !list[index + direction]) return;
    const next = [...list];
    [next[index], next[index + direction]] = [next[index + direction], next[index]];
    await Promise.all(
      next
        .map((policy, position) => ({ policy, position }))
        .filter(({ policy, position }) => policy.position !== position)
        .map(({ policy, position }) => api.patch(apiSlaPolicyPath(policy.id), { position })),
    );
    await invalidate();
  };

  const summary = (policy: SlaPolicy) =>
    [
      policy.priorities.length > 0
        ? policy.priorities.map((priority) => PRIORITY_META[priority].label).join("/")
        : "any priority",
      policy.issue_type_ids.length > 0
        ? policy.issue_type_ids.map((id) => typeName.get(id) ?? "?").join("/")
        : "any type",
      policy.reporter_team_ids.length > 0
        ? `reporter in ${policy.reporter_team_ids.length} team${policy.reporter_team_ids.length === 1 ? "" : "s"}`
        : null,
      policy.response_minutes !== null
        ? `response ${minutesLabel(policy.response_minutes)} (${metRuleSummary(policy.response_met_on, names(policy.response_state_ids), policy.response_team_ids.length)})`
        : "response —",
      policy.resolution_minutes !== null
        ? `resolution ${minutesLabel(policy.resolution_minutes)} (${metRuleSummary(policy.resolution_met_on, names(policy.resolution_state_ids), policy.resolution_team_ids.length)})`
        : "resolution —",
      policy.warning_minutes !== null
        ? `warn ${minutesLabel(policy.warning_minutes)} before`
        : null,
      windowLabel(policy.business_start_minute, policy.business_end_minute),
      policy.work_week_only ? "work week only" : null,
      policy.pause_state_names.length > 0
        ? `pauses in ${policy.pause_state_names.join(", ")}`
        : null,
    ]
      .filter(Boolean)
      .join(" · ");

  return (
    <SettingsPage history={{ entities: ["sla_policy"], projectId }}
      title="SLAs"
      description="Response and resolution targets for this project's service desk. For each issue, the first enabled policy from the top whose filters match is the one that applies — put specific tiers above catch-alls. Timers pause in a policy's pause states; breaches notify the assignee and watchers."
    >
      {!projectId || policies.isPending ? (
        <TableSkeleton rows={3} />
      ) : policies.isError ? (
        <QueryError label="SLA policies" error={policies.error} />
      ) : (
        <>
          {list.length === 0 ? (
            <EmptyState icon={Timer} message="No SLA policies for this project yet." />
          ) : (
            <ul className="rounded-lg border border-subtle">
              {list.map((policy, index) => (
                <Fragment key={policy.id}>
                <li
                  data-sla-policy={policy.name}
                  className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0"
                >
                  {canManage && (
                    <span className="flex flex-col text-fg-faint">
                      <button
                        type="button"
                        disabled={index === 0}
                        onClick={() => void move(index, -1)}
                        aria-label={`Move ${policy.name} up`}
                        className="cursor-pointer hover:text-fg disabled:opacity-30 disabled:cursor-default"
                      >
                        <ChevronUp size={13} />
                      </button>
                      <button
                        type="button"
                        disabled={index === list.length - 1}
                        onClick={() => void move(index, 1)}
                        aria-label={`Move ${policy.name} down`}
                        className="cursor-pointer hover:text-fg disabled:opacity-30 disabled:cursor-default"
                      >
                        <ChevronDown size={13} />
                      </button>
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium text-heading">
                      {policy.name}
                    </span>
                    <span className="block text-xs text-fg-muted">{summary(policy)}</span>
                  </span>
                  {canManage ? (
                    <>
                      <button
                        type="button"
                        onClick={() => toggle.mutate(policy)}
                        role="switch"
                        aria-checked={policy.enabled}
                        className={
                          "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide cursor-pointer " +
                          (policy.enabled
                            ? "bg-emerald-500/15 text-emerald-300"
                            : "bg-elevated text-fg-muted")
                        }
                      >
                        {policy.enabled ? "Enabled" : "Disabled"}
                      </button>
                      {/* RADD-1300: edit in place — same id, same position, so the
                          policy's per-issue bookkeeping and history survive. */}
                      <button
                        type="button"
                        onClick={() => setEditingId(editingId === policy.id ? null : policy.id)}
                        aria-label={`Edit ${policy.name}`}
                        aria-expanded={editingId === policy.id}
                        className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
                      >
                        <Pencil size={13} aria-hidden />
                      </button>
                      <button
                        type="button"
                        onClick={() => remove.mutate(policy.id)}
                        aria-label={`Delete ${policy.name}`}
                        className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-red-300 cursor-pointer"
                      >
                        <Trash2 size={13} aria-hidden />
                      </button>
                    </>
                  ) : (
                    !policy.enabled && (
                      <span className="text-[10px] uppercase text-fg-faint">Disabled</span>
                    )
                  )}
                </li>
                {editingId === policy.id && (
                  <li className="border-b border-subtle/60 px-4 py-3 last:border-b-0">
                    <SlaPolicyForm
                      projectId={projectId}
                      nextPosition={list.length}
                      policy={policy}
                      onDone={() => {
                        setEditingId(null);
                        void invalidate();
                      }}
                    />
                  </li>
                )}
                </Fragment>
              ))}
            </ul>
          )}
          {canManage && editingId === null && <SlaPolicyForm projectId={projectId} nextPosition={list.length} />}

          {/* RADD-930: CSAT arrived here from project → General. It is the other
              half of the service-desk loop these policies open — the survey
              fires when the item the timers were running against resolves. */}
          <section aria-label="Satisfaction surveys" className="mt-8">
            <h3 className="text-[13px] font-semibold text-heading">After resolution</h3>
            <p className="mb-3 mt-0.5 text-xs text-fg-muted">
              What happens once the timers above stop.
            </p>
            <ScopedSettingsEditor
              scope={SettingScope.project}
              scopeId={projectId}
              section="sla"
              emptyLabel="No post-resolution settings — the CSAT plugin is disabled."
            />
          </section>
        </>
      )}
    </SettingsPage>
  );
}
