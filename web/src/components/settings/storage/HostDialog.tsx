import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../../lib/api";
import { ApiPath, apiStorageHostPath } from "../../../lib/constants";
import { instanceStatusQuery, queryKeys } from "../../../lib/queries";
import {
  DeliveryMode,
  StorageHostType,
  type DeliveryModeValue,
  type StorageHostCreatePayload,
  type StorageHostRead,
  type StorageHostTypeValue,
  type StorageHostUpdatePayload,
} from "../../../lib/types";
import { Button } from "../../Button";
import { Modal } from "../../Modal";
import { SelectField } from "../../SelectField";
import { TextField } from "../../TextField";
import { ChangeHistoryPanel } from "../../history/ChangeHistoryPanel";

/** Labeled checkbox with an indented help line (the NewFieldModal idiom). */
function CheckboxField({
  label,
  help,
  checked,
  onChange,
  disabled,
  title,
}: {
  label: string;
  help?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <div title={title}>
      <label className="flex items-center gap-2 text-[13px] text-fg">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
          className="size-3.5 accent-accent"
        />
        {label}
      </label>
      {help && <p className="mt-0.5 pl-[22px] text-xs text-fg-muted">{help}</p>}
    </div>
  );
}

/**
 * Create/edit one storage host (spec 102). The type is immutable after
 * creation (the update schema has no host_type); a filesystem host can only
 * deliver via proxy, so the presigned option is disabled up front (spec-96
 * idiom) rather than 409ing on save.
 */
export function HostDialog({
  existing,
  onClose,
}: {
  existing: StorageHostRead | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(existing?.name ?? "");
  const [hostType, setHostType] = useState<StorageHostTypeValue>(
    existing?.host_type ?? StorageHostType.s3,
  );
  const [endpoint, setEndpoint] = useState(existing?.endpoint ?? "");
  const [accessKey, setAccessKey] = useState(existing?.access_key ?? "");
  const [secretKey, setSecretKey] = useState("");
  const [bucket, setBucket] = useState(existing?.bucket ?? "");
  const [region, setRegion] = useState(existing?.region ?? "");
  const [secure, setSecure] = useState(existing?.secure ?? false);
  const [rootDir, setRootDir] = useState(existing?.root_dir ?? "");
  const [delivery, setDelivery] = useState<DeliveryModeValue>(
    existing?.delivery_mode ?? DeliveryMode.proxy,
  );
  const [expiry, setExpiry] = useState(
    existing?.presign_expiry_seconds != null ? String(existing.presign_expiry_seconds) : "",
  );
  const [userSelectable, setUserSelectable] = useState(existing?.user_selectable ?? false);
  const [isDefault, setIsDefault] = useState(existing?.is_default ?? false);

  const isS3 = hostType === StorageHostType.s3;
  const isFilesystem = hostType === StorageHostType.filesystem;

  const onTypeChange = (next: StorageHostTypeValue) => {
    setHostType(next);
    // The backend rejects filesystem+presigned — snap back rather than 409 later.
    if (next === StorageHostType.filesystem) setDelivery(DeliveryMode.proxy);
  };

  const save = useMutation({
    mutationFn: (body: StorageHostCreatePayload | StorageHostUpdatePayload) =>
      existing
        ? api.patch<StorageHostRead>(apiStorageHostPath(existing.id), body)
        : api.post<StorageHostRead>(ApiPath.storageHosts, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.storageHosts });
      void queryClient.invalidateQueries({ queryKey: instanceStatusQuery.queryKey });
      onClose();
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    const shared: StorageHostUpdatePayload = {
      name: name.trim(),
      delivery_mode: delivery,
      presign_expiry_seconds: expiry.trim() === "" ? null : Number(expiry),
      user_selectable: userSelectable,
      is_default: isDefault,
      ...(isS3
        ? {
            endpoint: endpoint.trim(),
            access_key: accessKey.trim(),
            // "" on update = keep the stored secret (reads are redacted).
            secret_key: secretKey,
            bucket: bucket.trim(),
            region: region.trim(),
            secure,
          }
        : { root_dir: rootDir.trim() }),
    };
    save.mutate(existing ? shared : { ...shared, host_type: hostType });
  };

  return (
    <Modal title={existing ? "Edit host" : "Add storage host"} onClose={onClose}>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <TextField
          label="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Zoned S3"
          maxLength={200}
          required
        />
        <SelectField
          label="Type"
          value={hostType}
          onChange={(event) => onTypeChange(event.target.value as StorageHostTypeValue)}
          disabled={Boolean(existing)}
          title={existing ? "The host type is fixed after creation" : undefined}
          hint={existing ? "Fixed after creation — add a new host to change type." : undefined}
        >
          <option value={StorageHostType.s3}>S3-compatible</option>
          <option value={StorageHostType.filesystem}>Filesystem</option>
        </SelectField>
        {isS3 ? (
          <>
            <TextField
              label="Endpoint"
              value={endpoint}
              onChange={(event) => setEndpoint(event.target.value)}
              placeholder="s3.zone.example.com:3900 — no scheme"
              maxLength={500}
              required
            />
            <TextField
              label="Access key"
              value={accessKey}
              onChange={(event) => setAccessKey(event.target.value)}
              maxLength={200}
            />
            <TextField
              label="Secret key"
              type="password"
              autoComplete="new-password"
              value={secretKey}
              onChange={(event) => setSecretKey(event.target.value)}
              placeholder={existing?.has_secret_key ? "••••••••" : ""}
              hint={existing ? "Leave empty to keep the stored key." : undefined}
            />
            <TextField
              label="Bucket"
              value={bucket}
              onChange={(event) => setBucket(event.target.value)}
              maxLength={200}
              required
            />
            <TextField
              label="Region"
              value={region}
              onChange={(event) => setRegion(event.target.value)}
              maxLength={100}
              hint={"Must match the server's configured region when it enforces one — Garage's default is 'garage'; AWS ignores empty."}
            />
            <CheckboxField
              label="Secure (TLS)"
              help="Talk to the endpoint over https."
              checked={secure}
              onChange={setSecure}
            />
          </>
        ) : (
          <TextField
            label="Root directory"
            value={rootDir}
            onChange={(event) => setRootDir(event.target.value)}
            placeholder="server default attachments directory"
            maxLength={500}
            hint="Leave empty for the server's configured attachments directory."
          />
        )}
        <SelectField
          label="Delivery"
          value={delivery}
          onChange={(event) => setDelivery(event.target.value as DeliveryModeValue)}
          hint="Proxy streams bytes through Radd; presigned redirects the browser to fetch straight from the host."
        >
          <option value={DeliveryMode.proxy}>Proxy through the API</option>
          <option
            value={DeliveryMode.presigned}
            disabled={isFilesystem}
            title={isFilesystem ? "A filesystem host can only deliver via proxy" : undefined}
          >
            Presigned (browser fetches from the host)
          </option>
        </SelectField>
        {delivery === DeliveryMode.presigned && (
          <TextField
            label="Presign expiry (seconds)"
            type="number"
            min={30}
            max={86400}
            value={expiry}
            onChange={(event) => setExpiry(event.target.value)}
            placeholder="server default"
            hint="How long a minted download URL stays valid."
          />
        )}
        <CheckboxField
          label="User-selectable"
          help="Offered to users when a user-choice routing rule is active."
          checked={userSelectable}
          onChange={setUserSelectable}
        />
        <CheckboxField
          label="Default host"
          help="Receives every upload no routing rule claims."
          checked={isDefault}
          onChange={setIsDefault}
          disabled={existing?.is_default}
          title={
            existing?.is_default ? "Promote another host to change the default" : undefined
          }
        />
        <div className="mt-1 flex items-center justify-end gap-2">
          {save.isError && (
            <span className="mr-auto text-xs text-red-400">{errorMessage(save.error)}</span>
          )}
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending || !name.trim()}>
            {save.isPending ? "Saving…" : existing ? "Save changes" : "Add host"}
          </Button>
        </div>
        {existing && <ChangeHistoryPanel entityType="storage_host" entityId={existing.id} />}
      </form>
    </Modal>
  );
}
