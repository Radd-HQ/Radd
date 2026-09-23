import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiProjectThreadResolutionPath } from "../../lib/constants";
import { issueTypesQuery, queryKeys, threadResolutionQuery } from "../../lib/queries";
import {
  ThreadResolvers,
  type Project,
  type ThreadResolutionPolicy,
  type ThreadResolversValue,
} from "../../lib/types";
import { Button } from "../Button";
import { IconButton } from "../IconButton";
import { SelectField } from "../SelectField";

const RESOLVER_LABELS: Record<ThreadResolversValue, string> = {
  [ThreadResolvers.author]: "The thread's author and project managers",
  [ThreadResolvers.assignee]: "The author, the issue's assignee and project managers",
  [ThreadResolvers.anyone]: "Anyone who can comment on the issue",
  [ThreadResolvers.managers]: "Project managers only",
};

// A plain array, not a component: SelectField reads its <option> children directly.
const resolverOptions = () => Object.values(ThreadResolvers).map((value) => (
  <option key={value} value={value}>{RESOLVER_LABELS[value]}</option>
));

/**
 * Who may resolve a thread (RADD-1283): a project default plus per-issue-type
 * rules. Every change PUTs the whole policy and writes the server's answer into
 * the cache before the controls re-enable — the TransitionRow race, avoided
 * here from the start. The server applies the rule; threads carry `can_resolve`.
 */
export function ThreadResolutionSection({ project }: { project: Project }) {
  const client = useQueryClient();
  const policy = useQuery(threadResolutionQuery(project.id));
  const types = useQuery(issueTypesQuery(project.id));
  const save = useMutation({
    mutationFn: (next: ThreadResolutionPolicy) =>
      api.put<ThreadResolutionPolicy>(apiProjectThreadResolutionPath(project.id), next),
    onSuccess: (saved) => client.setQueryData(queryKeys.threadResolution(project.id), saved),
    // Threads' `can_resolve` depends on this rule.
    onSettled: () => invalidateEntities(client, Entity.comment),
  });

  const current = policy.data;
  const typeName = new Map((types.data ?? []).map((type) => [type.id, type.name]));
  const unused = (types.data ?? []).filter(
    (type) => !current?.overrides.some((override) => override.issue_type_id === type.id),
  );
  const put = (next: Partial<ThreadResolutionPolicy>) => current && save.mutate({ ...current, ...next });

  return (
    <section className="mt-8" data-thread-resolution-settings>
      <h3 className="text-sm font-medium text-heading">Who can resolve threads</h3>
      <p className="mt-1 text-xs text-fg-muted">
        Applies to resolvable threads on this project's issues. An issue-type rule overrides the
        default for issues of that type. The same people can unresolve a thread, or reply and
        unresolve it. Project managers can always resolve, and under &quot;Project managers
        only&quot; nobody else can.
      </p>
      {policy.isError && <p role="alert" className="mt-2 text-xs text-status-danger-ink">{errorMessage(policy.error)}</p>}
      {current && (
        <div className="mt-3 flex flex-col gap-3 rounded-lg border border-subtle p-4">
          <SelectField
            label="Default"
            className="max-w-md"
            value={current.default}
            disabled={save.isPending}
            onChange={(event) => put({ default: event.target.value as ThreadResolversValue })}
          >
            {resolverOptions()}
          </SelectField>
          {current.overrides.length > 0 && (
            <ul className="flex flex-col gap-2" aria-label="Issue-type rules">
              {current.overrides.map((override, index) => (
                <li key={override.issue_type_id} className="flex items-end gap-2" data-thread-rule={override.issue_type_id}>
                  <SelectField
                    label={index === 0 ? "Issue type" : ""}
                    ariaLabel="Issue type"
                    className="w-48 shrink-0"
                    value={override.issue_type_id}
                    disabled={save.isPending}
                    onChange={(event) => put({
                      overrides: current.overrides.map((row, at) =>
                        at === index ? { ...row, issue_type_id: event.target.value } : row),
                    })}
                  >
                    <option value={override.issue_type_id}>{typeName.get(override.issue_type_id) ?? "Unknown type"}</option>
                    {unused.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
                  </SelectField>
                  <SelectField
                    label={index === 0 ? "Who can resolve" : ""}
                    ariaLabel="Who can resolve"
                    className="min-w-0 flex-1"
                    value={override.resolvers}
                    disabled={save.isPending}
                    onChange={(event) => put({
                      overrides: current.overrides.map((row, at) =>
                        at === index ? { ...row, resolvers: event.target.value as ThreadResolversValue } : row),
                    })}
                  >
                    {resolverOptions()}
                  </SelectField>
                  <IconButton
                    aria-label={`Remove the rule for ${typeName.get(override.issue_type_id) ?? "this type"}`}
                    disabled={save.isPending}
                    onClick={() => put({ overrides: current.overrides.filter((_, at) => at !== index) })}
                  >
                    <X size={13} />
                  </IconButton>
                </li>
              ))}
            </ul>
          )}
          {unused.length > 0 && (
            <Button
              size="sm"
              variant="ghost"
              className="self-start"
              disabled={save.isPending}
              data-add-thread-rule
              onClick={() => put({
                overrides: [...current.overrides, { issue_type_id: unused[0].id, resolvers: current.default }],
              })}
            >
              <Plus size={13} aria-hidden />
              Add an issue-type rule
            </Button>
          )}
          {save.isError && <p role="alert" className="text-xs text-status-danger-ink">{errorMessage(save.error)}</p>}
        </div>
      )}
    </section>
  );
}
