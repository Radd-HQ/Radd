import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarRange, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiCycleSeriesPath } from "../../lib/constants";
import { WEEKDAY_LABELS } from "../../lib/cycle-series";
import { Entity, invalidateEntities } from "../../lib/cache";
import { cycleSeriesPageQuery, CYCLES_PAGE_SIZE } from "../../lib/queries/cycles";
import { useDirectory } from "../../lib/useDirectory";
import type { CycleSeries, CycleSeriesUpdate } from "../../lib/types";
import { Button } from "../Button";
import { DirectoryPager } from "../DirectoryPager";
import { EmptyState } from "../EmptyState";
import { IconButton } from "../IconButton";
import { QueryError } from "../QueryError";
import { Select } from "../Select";
import { TableSkeleton } from "../TableSkeleton";
import { TextField } from "../TextField";

/** Recurring series: per-label auto-provisioning config (created via the New-cycle
 * modal's Recurring checkbox; look-ahead + next number editable here). */
export function SeriesSection({ canManage, canDelete }: { canManage: boolean; canDelete: boolean }) {
  const series = useDirectory("cycle-series", CYCLES_PAGE_SIZE, cycleSeriesPageQuery);
  // A deletion may remove the only row on the last page. Return to the last
  // nonempty window without requiring an extra click or hiding the controls.
  const lastPage = Math.max(0, Math.ceil(series.total / series.pageSize) - 1);
  if (series.isSuccess && series.page > lastPage) series.setPage(lastPage);
  return <section className="mt-6" aria-label="Recurring series" aria-busy={series.busy}>
    <h2 className="mb-1 text-sm font-semibold text-fg">Recurring series</h2>
    <p className="mb-2 text-xs text-fg-muted">
      Each label keeps its configured number of future cycles ready — drafts are created
      automatically when a cycle of the label is created or completed.
    </p>
    <div className="mb-3"><TextField type="search" label="Find recurring series"
      placeholder="Search labels…" value={series.filter} onChange={event => series.setFilter(event.target.value)} /></div>
    {series.isPending ? <TableSkeleton rows={3} />
      : series.isError ? <div className="space-y-2"><QueryError label="recurring series" error={series.error} />
        <Button variant="secondary" onClick={() => void series.refetch()}>Retry series</Button></div>
      : series.rows.length === 0 ? <EmptyState icon={CalendarRange}
        message={series.filter ? "No recurring series match your search." : "No recurring series. Enable Recurring when creating a cycle to keep future cycles ready."} />
      : <ul className="rounded-lg border border-subtle">{series.rows.map(row =>
        <SeriesRow key={row.id} series={row} canManage={canManage} canDelete={canDelete} />
      )}</ul>}
    <DirectoryPager {...series} onPage={series.setPage} label="recurring series" />
  </section>;
}

function seriesDraft(base: CycleSeries) {
  return { base, draftsAhead: String(base.drafts_ahead), nextNumber: String(base.next_number),
    weekday: base.start_weekday === null ? "" : String(base.start_weekday),
    duration: String(base.duration_days ?? 14) };
}
function seriesDirty(draft: ReturnType<typeof seriesDraft>) {
  return Number(draft.draftsAhead) !== draft.base.drafts_ahead ||
    Number(draft.nextNumber) !== draft.base.next_number ||
    (draft.weekday === "" ? null : Number(draft.weekday)) !== draft.base.start_weekday ||
    (draft.weekday === "" ? null : Number(draft.duration)) !== draft.base.duration_days;
}

function SeriesRow({ series, canManage, canDelete }: { series: CycleSeries; canManage: boolean; canDelete: boolean }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => seriesDraft(series));
  useEffect(() => {
    // Live refresh updates idle inputs; an unfinished edit stays with its author.
    setDraft(current => seriesDirty(current) ? current : seriesDraft(series));
  }, [series]);
  const { draftsAhead, nextNumber, weekday, duration } = draft;
  const dirty = seriesDirty(draft);
  const setValue = (key: "draftsAhead" | "nextNumber" | "weekday" | "duration", value: string) =>
    setDraft(current => ({ ...current, [key]: value }));

  const invalidate = () => {
    void invalidateEntities(queryClient, Entity.cycleSeries, Entity.cycle);
  };
  const save = useMutation({
    mutationFn: () =>
      api.patch<CycleSeries>(apiCycleSeriesPath(series.id), {
        drafts_ahead: Number(draftsAhead),
        next_number: Number(nextNumber),
        // "" = clear the cadence (explicit nulls) → back to dateless drafts
        start_weekday: weekday === "" ? null : Number(weekday),
        duration_days: weekday === "" ? null : Number(duration),
      } satisfies CycleSeriesUpdate),
    onSuccess: updated => {
      setDraft(seriesDraft(updated));
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiCycleSeriesPath(series.id)),
    onSuccess: invalidate,
  });

  return (
    <li className="flex flex-wrap items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
      <span className="text-[13px] font-medium text-heading">{series.label}</span>
      <label className="ml-auto flex items-center gap-1.5 text-xs text-fg-secondary">
        Starts
        <Select
          value={weekday}
          onChange={value => setValue("weekday", value)}
          disabled={!canManage}
          size="sm"
          aria-label="Starts"
          options={[
            { value: "", label: "Unscheduled" },
            ...WEEKDAY_LABELS.map((label, index) => ({
              value: String(index),
              label: `${label}s`,
            })),
          ]}
        />
      </label>
      <label className="flex items-center gap-1.5 text-xs text-fg-secondary">
        Days
        <input
          type="number"
          min={1}
          max={90}
          value={duration}
          disabled={!canManage || weekday === ""}
          onChange={(event) => setValue("duration", event.target.value)}
          className="h-7 w-14 rounded-md border border-strong bg-surface px-1.5 text-xs text-heading disabled:opacity-60"
        />
      </label>
      <label className="flex items-center gap-1.5 text-xs text-fg-secondary">
        Drafts ahead
        <input
          type="number"
          min={0}
          max={20}
          value={draftsAhead}
          onChange={(event) => setValue("draftsAhead", event.target.value)}
          disabled={!canManage}
          className="h-7 w-16 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading disabled:opacity-60"
        />
      </label>
      <label className="flex items-center gap-1.5 text-xs text-fg-secondary">
        Next number
        <input
          type="number"
          min={1}
          value={nextNumber}
          onChange={(event) => setValue("nextNumber", event.target.value)}
          disabled={!canManage}
          className="h-7 w-20 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading disabled:opacity-60"
        />
      </label>
      {canManage && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => save.mutate()}
            disabled={!dirty || save.isPending}
          >
            {save.isPending ? "Saving…" : "Save"}
          </Button>
      )}
      {canDelete && (
          <IconButton
            danger
            onClick={() => remove.mutate()}
            title="Stop recurring (existing cycles are kept)"
            aria-label="Stop recurring"
          >
            <Trash2 size={13} />
          </IconButton>
      )}
      {(save.isError || remove.isError) && (
        <span className="w-full text-xs text-status-danger-ink">
          {errorMessage(save.error ?? remove.error)}
        </span>
      )}
    </li>
  );
}

