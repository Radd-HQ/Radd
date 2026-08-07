import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Clock, Plus } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiWorkCategoryPath, ApiPath } from "../../lib/constants";
import { usePermissions, usePluginEnabled } from "../../lib/hooks";
import { workCategoriesQuery } from "../../lib/queries";
import {
  Permission,
  SettingScope,
  type WorkCategory,
  type WorkCategoryCreate,
  type WorkCategoryUpdate,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { TeamHolidaysSection } from "../../components/settings/LeaveSections";
import { ScopedSettingsEditor } from "../../components/settings/ScopedSettingsEditor";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { IconButton } from "../../components/IconButton";

/**
 * Instance-wide time-logging admin (spec 50; RADD-932).
 *
 * Was "Work categories" — a tab named after one of its sections. It now holds
 * every instance-scope answer to "what is a working day here, and how much of
 * one": the shared categories, what a `1d` duration means, the timesheet's
 * under/over-logged thresholds, the default working week, and per-team public
 * holidays (previously a separate People-group tab).
 *
 * Holidays belong at THIS scope, not under a project's Time logging tab: they
 * are per-TEAM and feed both the timesheet's away cells and business-day SLA
 * resolution, so a project is the wrong axis for them entirely. Per-project
 * ENABLEMENT stays under each project.
 */
export function TimeloggingSettingsPage() {
  // `leave` is an optional plugin — with it disabled the endpoint is unmounted,
  // so the section is dropped rather than left to render a 404 (RADD-928).
  const leaveEnabled = usePluginEnabled("leave");

  return (
    <SettingsPage
      title="Time logging"
      description="Instance-wide time policy: the categories people pick, what a working day means, and the holidays that interrupt it. Enable time logging for a project from that project's settings."
    >
      <Section
        title="Work categories"
        hint="What people pick when logging time. Archived categories stay on old worklogs but leave the picker."
      >
        <CategoriesSection />
      </Section>

      <Section
        title="What a working day means"
        hint="Durations, the default working week, and the thresholds the timesheet flags a day against. A project can override the working week under its own Time logging tab."
      >
        <ScopedSettingsEditor scope={SettingScope.instance} section="timelogging" />
      </Section>

      {leaveEnabled && (
        <Section
          title="Holidays"
          hint="Per-team public holidays — regional teams differ, which is the point. They mark every current member of the team away on the timesheet and exempt those days from the outlier flags above."
        >
          <TeamHolidaysSection />
        </Section>
      )}
    </SettingsPage>
  );
}

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="mb-8 last:mb-0">
      <h3 className="text-[13px] font-semibold text-heading">{title}</h3>
      <p className="mb-3 mt-0.5 text-xs text-fg-muted">{hint}</p>
      {children}
    </section>
  );
}

function CategoriesSection() {
  const perms = usePermissions();
  const canManage = perms.global(Permission.globalManage);
  // Admins see archived too so they can restore; the picker (issue page) hides them.
  const categories = useQuery(workCategoriesQuery(true));
  const list = categories.data ?? [];

  return (
    <section>
      {categories.isPending ? (
        <TableSkeleton rows={4} />
      ) : list.length === 0 ? (
        <EmptyState icon={Clock} message="No work categories yet." />
      ) : (
        <ul className="rounded-lg border border-subtle">
          {list.map((category) => (
            <CategoryRow key={category.id} category={category} canManage={canManage} />
          ))}
        </ul>
      )}
      {canManage && <AddCategory />}
    </section>
  );
}

function CategoryRow({
  category,
  canManage,
}: {
  category: WorkCategory;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(category.name);
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["workCategories"] });

  const patch = useMutation({
    mutationFn: (body: WorkCategoryUpdate) =>
      api.patch<WorkCategory>(apiWorkCategoryPath(category.id), body),
    onSuccess: invalidate,
  });

  return (
    <li
      className={`flex items-center gap-3 border-b border-subtle/60 px-4 py-2 last:border-b-0 ${
        category.archived ? "opacity-50" : ""
      }`}
    >
      {canManage ? (
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          onBlur={() => {
            const trimmed = name.trim();
            if (trimmed && trimmed !== category.name) patch.mutate({ name: trimmed });
            else setName(category.name);
          }}
          className="flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 text-[13px] text-heading hover:border-subtle focus:border-strong focus:outline-2 focus:outline-offset-1 focus:outline-focus"
        />
      ) : (
        <span className="flex-1 text-[13px] text-fg">{category.name}</span>
      )}
      {category.archived && (
        <span className="rounded border border-strong px-1.5 py-px text-[10px] uppercase tracking-wide text-fg-muted">
          Archived
        </span>
      )}
      {canManage && (
        <IconButton
          onClick={() => patch.mutate({ archived: !category.archived })}
          disabled={patch.isPending}
          aria-label={category.archived ? "Restore category" : "Archive category"}
        >
          {category.archived ? <ArchiveRestore size={13} /> : <Archive size={13} />}
        </IconButton>
      )}
    </li>
  );
}

function AddCategory() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api.post<WorkCategory>(ApiPath.workCategories, {
        name: name.trim(),
      } satisfies WorkCategoryCreate),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workCategories"] });
      setName("");
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) create.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="mt-3 flex items-end gap-2">
      <TextField
        label="New category"
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="e.g. Bug fixing"
        maxLength={100}
      />
      <Button type="submit" disabled={create.isPending || !name.trim()} className="self-end">
        <Plus size={14} aria-hidden />
        Add
      </Button>
      {create.isError && (
        <span className="self-center text-xs text-red-400">{errorMessage(create.error)}</span>
      )}
    </form>
  );
}
