import { useState, type FormEvent } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { ApiPath, RoutePath, apiDashboardPath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import type { Dashboard, DashboardCreate, DashboardUpdate } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { TextField } from "../TextField";
import { ErrorText } from "../ErrorText";

/**
 * New/Edit dashboard dialog (spec 75). Create takes just a name (any member —
 * sharing comes later via the Sharing dialog); edit adds the description.
 * On create we jump straight into the fresh (empty) dashboard.
 */
export function DashboardModal({
  dashboard,
  onClose,
}: {
  /** When set, edit this dashboard in place instead of creating one. */
  dashboard?: Dashboard;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState(dashboard?.name ?? "");
  const [description, setDescription] = useState(dashboard?.description ?? "");

  const save = useMutation({
    mutationFn: async () => {
      if (dashboard) {
        return api.patch<Dashboard>(apiDashboardPath(dashboard.id), {
          name: name.trim(),
          description: description.trim(),
        } satisfies DashboardUpdate);
      }
      return api.post<Dashboard>(ApiPath.dashboards, {
        name: name.trim(),
      } satisfies DashboardCreate);
    },
    onSuccess: async (saved) => {
      await invalidateEntities(queryClient, Entity.dashboard);
      onClose();
      if (!dashboard) {
        void navigate({ to: RoutePath.dashboard, params: { dashboardId: saved.id } });
      }
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) save.mutate();
  };

  return (
    <Modal title={dashboard ? "Edit dashboard" : "New dashboard"} onClose={onClose}>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <TextField
          label="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Team delivery"
          maxLength={100}
          required
        />
        {dashboard && (
          <TextField
            label="Description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What this dashboard tracks (optional)"
            maxLength={2000}
          />
        )}
        {save.isError && <ErrorText error={save.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!name.trim() || save.isPending}>
            {save.isPending ? "Saving…" : dashboard ? "Save" : "Create dashboard"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
