import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { api, Button, ErrorText, useConfirm } from "@radd/plugin-sdk";
import type { ConsumerFailure, ReplayResult } from "./types";
import { Card } from "./cards";

const FAILURES_POLL_MS = 10_000;

/** Events a background worker could not handle (RADD-1538). Pending ones are
 * being retried by the worker itself; dead ones wait here for a decision —
 * replay hands the event to its worker again, discard gives up on it. Renders
 * nothing while there are none, which is the normal state. */
export function FailedEvents({ expected }: { expected: number }) {
  const client = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const failures = useQuery({
    queryKey: ["consumerFailures"],
    queryFn: ({ signal }) => api.get<ConsumerFailure[]>("/events/failures", { signal }),
    refetchInterval: FAILURES_POLL_MS,
    enabled: expected > 0,
  });
  const settle = () => {
    void client.invalidateQueries({ queryKey: ["consumerFailures"] });
    void client.invalidateQueries({ queryKey: ["monitoringOverview"] });
  };
  const replay = useMutation({
    mutationFn: (id: number) => api.post<ReplayResult>(`/events/failures/${id}/replay`, {}),
    onSettled: settle,
  });
  const discard = useMutation({
    mutationFn: (id: number) => api.delete(`/events/failures/${id}`),
    onSettled: settle,
  });

  if (expected === 0 || !failures.data?.length) return null;
  const failedAgain = replay.data && !replay.data.delivered;

  return (
    <div className="lg:col-span-2" data-failed-events>
      <Card icon={TriangleAlert} title="Failed events">
        <p className="mb-2 text-xs text-fg-muted">
          A worker raised an error handling these events. Retrying ones are attempted again
          automatically; the rest stay until someone replays or discards them.
        </p>
        {failedAgain && (
          <ErrorText error={`The replay failed again: ${replay.data?.failure?.error ?? ""}`} />
        )}
        {replay.isError && <ErrorText error={replay.error} />}
        <table className="w-full text-row">
          <thead>
            <tr className="text-left text-meta uppercase tracking-wide text-fg-faint">
              <th className="py-1 pr-3 font-medium">Worker</th>
              <th className="py-1 pr-3 font-medium">Event</th>
              <th className="py-1 pr-3 font-medium">Error</th>
              <th className="py-1 pr-3 font-medium">Attempts</th>
              <th className="py-1 font-medium" />
            </tr>
          </thead>
          <tbody className="divide-y divide-subtle/60">
            {failures.data.map((failure) => (
              <tr key={failure.id} data-failure={failure.status}>
                <td className="py-1.5 pr-3 align-top font-mono text-xs text-fg">{failure.consumer}</td>
                <td className="py-1.5 pr-3 align-top">
                  <span className="text-fg">{failure.event_type ?? "event removed"}</span>
                  <span className="block text-meta text-fg-muted">
                    {failure.entity_label ?? `#${failure.event_id}`}
                  </span>
                </td>
                <td className="max-w-md py-1.5 pr-3 align-top text-meta text-fg-secondary">
                  <span className="line-clamp-3 break-words" title={failure.error}>
                    {failure.error}
                  </span>
                </td>
                <td className="py-1.5 pr-3 align-top tabular-nums text-fg-secondary">
                  {failure.attempts}
                  <span className="block text-meta text-fg-muted">
                    {failure.status === "pending" ? "retrying" : "gave up"}
                  </span>
                </td>
                <td className="py-1.5 align-top">
                  <span className="flex justify-end gap-1.5">
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={replay.isPending}
                      onClick={() => replay.mutate(failure.id)}
                    >
                      Replay
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={discard.isPending}
                      onClick={async () => {
                        const sure = await confirm({
                          title: "Discard this failed event?",
                          message:
                            "Its side effect (a notification, a webhook, an automation run or an index update) will not happen.",
                          confirmLabel: "Discard",
                          danger: true,
                        });
                        if (sure) discard.mutate(failure.id);
                      }}
                    >
                      Discard
                    </Button>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {confirmDialog}
    </div>
  );
}
