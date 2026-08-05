import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Clock, Plus } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiWorkCategoryPath, ApiPath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { workCategoriesQuery } from "../../lib/queries";
import {
  Permission,
  type WorkCategory,
  type WorkCategoryCreate,
  type WorkCategoryUpdate,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { IconButton } from "../../components/IconButton";

/**
 * Global time-logging admin (spec 50): the shared work categories people pick
 * when logging. Per-project ENABLEMENT lives under each project
 * (`/p/$projectKey/settings/timelogging`), so this page stays global-only.
 */
export function TimeloggingSettingsPage() {
  return (
    <SettingsPage
      title="Work categories"
      description="Curate the work categories people pick when logging time. Enable time logging for a project from that project's settings."
    >
      <CategoriesSection />
    </SettingsPage>
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
