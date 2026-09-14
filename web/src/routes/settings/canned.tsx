import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquareQuote, Pencil, Plus, Trash2, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, apiCannedResponsePath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { usePermissions } from "../../lib/hooks";
import { useListFilter } from "../../lib/list-filter";
import { cannedResponsesQuery } from "../../lib/queries";
import { Permission, type CannedResponse } from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ListSearchInput } from "../../components/ListSearchInput";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";

/** Canned responses admin (spec 30): admin-managed comment snippets. */
export function CannedSettingsPage() {
  const perms = usePermissions();
  const canManage = perms.global(Permission.cannedUpdate);
  const responses = useQuery(cannedResponsesQuery());
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<CannedResponse | null>(null);

  const remove = useMutation({
    mutationFn: (responseId: string) => api.delete<void>(apiCannedResponsePath(responseId)),
    onSettled: () => invalidateEntities(queryClient, Entity.cannedResponse),
  });

  const all = responses.data ?? [];
  const search = useListFilter(all, (response) => [response.title]);
  const list = search.filtered;

  return (
    <SettingsPage history={{ entities: ["canned_response"] }}
      title="Canned responses"
      description="Reusable global reply snippets — anyone can insert them from the comment composer; managing them needs admin rights."
    >
      {responses.isPending ? (
        <TableSkeleton rows={3} />
      ) : responses.isError ? (
        <QueryError label="canned responses" error={responses.error} />
      ) : (
        <>
          {all.length === 0 ? (
            <EmptyState
              icon={MessageSquareQuote}
              message="No canned responses yet — the service-desk reply flow starts below."
            />
          ) : (
            <>
              {all.length > 8 && (
                <ListSearchInput
                  className="mb-3"
                  value={search.filter}
                  onChange={search.setFilter}
                  placeholder="Filter responses by title…"
                  total={all.length}
                  matched={list.length}
                  noun="responses"
                />
              )}
              {list.length === 0 ? (
                <EmptyState
                  icon={MessageSquareQuote}
                  message={`No responses match “${search.filter.trim()}”.`}
                />
              ) : (
                <ul className="rounded-lg border border-subtle">
                  {list.map((response) => (
                    <li
                      key={response.id}
                      className="border-b border-subtle/60 px-4 py-2.5 last:border-b-0"
                    >
                      <div className="flex items-center gap-2">
                        <span className="flex-1 text-[13px] font-medium text-heading">
                          {response.title}
                        </span>
                        {canManage && (
                          <>
                            <button
                              type="button"
                              onClick={() =>
                                setEditing(editing?.id === response.id ? null : response)
                              }
                              aria-label={`Edit ${response.title}`}
                              className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
                            >
                              <Pencil size={13} aria-hidden />
                            </button>
                            <button
                              type="button"
                              onClick={() => remove.mutate(response.id)}
                              aria-label={`Delete ${response.title}`}
                              className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-red-300 cursor-pointer"
                            >
                              <Trash2 size={13} aria-hidden />
                            </button>
                          </>
                        )}
                      </div>
                      <p className="mt-0.5 line-clamp-2 whitespace-pre-wrap text-xs text-fg-muted">
                        {response.body}
                      </p>
                      {editing?.id === response.id && (
                        <ResponseForm existing={response} onDone={() => setEditing(null)} />
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          {canManage && <ResponseForm />}
        </>
      )}
    </SettingsPage>
  );
}

function ResponseForm({
  existing,
  onDone,
}: {
  existing?: CannedResponse;
  onDone?: () => void;
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState(existing?.title ?? "");
  const [body, setBody] = useState(existing?.body ?? "");

  const save = useMutation({
    mutationFn: () =>
      existing
        ? api.patch<CannedResponse>(apiCannedResponsePath(existing.id), { title, body })
        : api.post<CannedResponse>(ApiPath.cannedResponses, {
            title,
            body,
          }),
    onSuccess: () => {
      if (!existing) {
        setTitle("");
        setBody("");
      }
      onDone?.();
    },
    onSettled: () => invalidateEntities(queryClient, Entity.cannedResponse),
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (title.trim() && body.trim()) save.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="mt-4 flex flex-col gap-3">
      <TextField
        label={existing ? "Title" : "New response title"}
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder="Restart the farm node"
        maxLength={200}
      />
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-fg-secondary">Body (markdown)</label>
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={3}
          placeholder="Please restart the render node and re-submit…"
          className="rounded-md border border-strong bg-surface px-2.5 py-2 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
      </div>
      <div className="flex items-center gap-2">
        <Button type="submit" disabled={save.isPending || !title.trim() || !body.trim()}>
          <Plus size={14} aria-hidden />
          {save.isPending ? "Saving…" : existing ? "Save changes" : "Create response"}
        </Button>
        {existing && (
          <button
            type="button"
            onClick={onDone}
            className="flex items-center gap-1 text-xs text-fg-muted hover:text-fg cursor-pointer"
          >
            <X size={12} aria-hidden />
            Cancel
          </button>
        )}
        {save.isError && (
          <span className="text-xs text-red-400">{errorMessage(save.error)}</span>
        )}
      </div>
    </form>
  );
}
