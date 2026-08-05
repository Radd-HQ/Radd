import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { ApiPath, PROJECT_KEY_HINT, PROJECT_KEY_PATTERN } from "../../lib/constants";
import { queryKeys } from "../../lib/queries";
import type { Project, ProjectCreate } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { TextField } from "../TextField";
import { ErrorText } from "../ErrorText";

interface NewProjectModalProps {
  onClose: () => void;
}

export function NewProjectModal({ onClose }: NewProjectModalProps) {
  const queryClient = useQueryClient();
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [keyError, setKeyError] = useState<string>();

  const createProject = useMutation({
    mutationFn: (body: ProjectCreate) => api.post<Project>(ApiPath.projects, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects });
      onClose();
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const trimmedKey = key.trim();
    if (!PROJECT_KEY_PATTERN.test(trimmedKey)) {
      setKeyError(`Invalid key: ${PROJECT_KEY_HINT}.`);
      return;
    }
    setKeyError(undefined);
    createProject.mutate({ key: trimmedKey, name: name.trim() });
  };

  return (
    <Modal title="New project" onClose={onClose}>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <TextField
          label="Key"
          value={key}
          onChange={(event) => setKey(event.target.value.toUpperCase())}
          placeholder="TD"
          hint={PROJECT_KEY_HINT}
          error={keyError}
          maxLength={10}
          required
        />
        <TextField
          label="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="TD Support"
          maxLength={200}
          required
        />
        {createProject.isError && (
          <ErrorText error={createProject.error} />
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={createProject.isPending || !key || !name}>
            {createProject.isPending ? "Creating…" : "Create project"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
