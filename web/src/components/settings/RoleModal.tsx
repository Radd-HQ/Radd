import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { ApiPath, ROLE_KEY_HINT, ROLE_KEY_PATTERN } from "../../lib/constants";
import { queryKeys } from "../../lib/queries";
import { withRelations, type PermissionInfo, type PermissionValue, type Role, type RoleCreate } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { TextField } from "../TextField";
import { PermissionMatrix } from "./PermissionMatrix";
import { ErrorText } from "../ErrorText";

interface RoleModalProps {
  catalog: PermissionInfo[];
  onClose: () => void;
  onCreated: (role: Role) => void;
}

/** "my Role" → "my-role" (client-side convenience; the key stays editable). */
function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
}

/** New custom role dialog: name, key, description + permission matrix. */
export function RoleModal({ catalog, onClose, onCreated }: RoleModalProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [keyTouched, setKeyTouched] = useState(false);
  const [description, setDescription] = useState("");
  const [permissions, setPermissions] = useState<PermissionValue[]>([]);

  const create = useMutation({
    mutationFn: (body: RoleCreate) => api.post<Role>(ApiPath.roles, body),
    onSuccess: async (role) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.roles });
      onCreated(role);
      onClose();
    },
  });

  const keyValid = ROLE_KEY_PATTERN.test(key);
  const canSubmit = name.trim().length > 0 && keyValid && !create.isPending;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    create.mutate({
      key,
      name: name.trim(),
      description: description.trim(),
      permissions,
    });
  };

  // RADD-939 — see the roles page: an atom's relations are a set.
  const setRelations = (permission: PermissionValue, relations: string[]) =>
    setPermissions((previous) => withRelations(previous, permission, relations));

  return (
    <Modal title="New role" onClose={onClose} wide>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Name"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              if (!keyTouched) setKey(slugify(event.target.value));
            }}
            placeholder="Triager"
            maxLength={100}
            required
          />
          <TextField
            label="Key"
            value={key}
            onChange={(event) => {
              setKeyTouched(true);
              setKey(event.target.value);
            }}
            placeholder="triager"
            error={key && !keyValid ? ROLE_KEY_HINT : undefined}
            hint={key && !keyValid ? undefined : ROLE_KEY_HINT}
            required
          />
        </div>
        <TextField
          label="Description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="What this role is for"
          maxLength={500}
        />
        <PermissionMatrix catalog={catalog} selected={permissions} onChange={setRelations} />
        {create.isError && <ErrorText error={create.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!canSubmit}>
            {create.isPending ? "Creating…" : "Create role"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
