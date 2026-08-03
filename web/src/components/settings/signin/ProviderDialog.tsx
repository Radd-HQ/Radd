import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Check } from "lucide-react";
import { api, errorMessage } from "../../../lib/api";
import { ApiPath, apiSsoProviderPath } from "../../../lib/constants";
import { instanceStatusQuery, queryKeys, rolesQuery, ssoKindsQuery } from "../../../lib/queries";
import {
  BASELINE_ROLE_KEY,
  SIGNUP_DOMAIN_WILDCARD,
  SsoKind,
  type SsoKindValue,
  type SsoProviderPayload,
  type SsoProviderRead,
} from "../../../lib/types";
import { Button } from "../../Button";
import { Modal } from "../../Modal";
import { SelectField } from "../../SelectField";
import { TextField } from "../../TextField";
import { TokenMultiSelect } from "../../TokenMultiSelect";

/** Labeled checkbox with an indented help line (the HostDialog idiom). */
function CheckboxField({
  label,
  help,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  help?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div>
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

/** The redirect URI to paste into the IdP's console — read-only, copyable. */
function RedirectUriField({ uri }: { uri: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <div className="mb-1 text-[13px] text-fg">Redirect URI</div>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-md border border-subtle bg-base px-2 py-1.5 text-xs text-fg-secondary">
          {uri}
        </code>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            void navigator.clipboard.writeText(uri);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <p className="mt-1 text-xs text-fg-muted">
        Add this as an authorized redirect URI in the provider&rsquo;s console. One URI serves
        every provider — the sign-in attempt carries which one it belongs to.
      </p>
    </div>
  );
}

/**
 * Create/edit one sign-in provider (spec 110).
 *
 * The kind is immutable after creation (it decides the discovery defaults the
 * row was built against). Google pins its own issuer, so that field only
 * appears for a generic OIDC provider — an admin adding Google pastes a client
 * id/secret and a domain list, nothing else.
 */
export function ProviderDialog({
  existing,
  onClose,
}: {
  existing: SsoProviderRead | null;
  onClose: () => void;
}) {
  const editing = existing !== null;
  const kinds = useQuery(ssoKindsQuery());
  const roles = useQuery(rolesQuery());
  const queryClient = useQueryClient();

  const [kind, setKind] = useState<SsoKindValue>(existing?.kind ?? SsoKind.google);
  const [name, setName] = useState(existing?.name ?? "");
  const [issuer, setIssuer] = useState(existing?.issuer ?? "");
  const [clientId, setClientId] = useState(existing?.client_id ?? "");
  const [clientSecret, setClientSecret] = useState("");
  const [enabled, setEnabled] = useState(existing?.enabled ?? true);
  const [autoProvision, setAutoProvision] = useState(existing?.auto_provision ?? true);
  const [domains, setDomains] = useState<string[]>(existing?.allowed_signup_domains ?? []);
  const [requireVerified, setRequireVerified] = useState(existing?.require_verified_email ?? true);
  const [groupClaim, setGroupClaim] = useState(existing?.group_claim ?? "groups");
  const [adminGroups, setAdminGroups] = useState(existing?.admin_groups ?? "");
  // The role a NEW account starts with (RADD-777). "" = the Baseline alone.
  const [defaultRoleId, setDefaultRoleId] = useState(existing?.default_role_id ?? "");
  const [error, setError] = useState("");

  const kindInfo = (kinds.data ?? []).find((k) => k.kind === kind);
  const isGoogle = kind === SsoKind.google;
  const wildcard = domains.includes(SIGNUP_DOMAIN_WILDCARD);

  const save = useMutation({
    mutationFn: async () => {
      const payload: SsoProviderPayload = {
        name: name.trim(),
        enabled,
        issuer: isGoogle ? "" : issuer.trim(),
        client_id: clientId.trim(),
        auto_provision: autoProvision,
        allowed_signup_domains: domains,
        require_verified_email: requireVerified,
        group_claim: groupClaim.trim() || "groups",
        admin_groups: adminGroups.trim(),
        default_role_id: defaultRoleId || null,
      };
      // An empty secret on update means "keep the stored one" — send it only
      // when the admin actually typed a replacement.
      if (clientSecret.trim()) payload.client_secret = clientSecret.trim();
      if (editing) return api.patch(apiSsoProviderPath(existing.id), payload);
      return api.post(ApiPath.ssoProviders, { ...payload, kind });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ssoProviders });
      void queryClient.invalidateQueries({ queryKey: instanceStatusQuery.queryKey });
      onClose();
    },
    onError: (err) => setError(errorMessage(err)),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError("");
    save.mutate();
  };

  return (
    // `wide` is load-bearing, not cosmetic: only the wide/extraWide panels carry
    // `max-h-full overflow-y-auto`, and this form is taller than a 900px viewport
    // — on the default panel the Save button sits below the fold, unreachable.
    <Modal
      wide
      onClose={onClose}
      title={editing ? `Edit ${existing.name}` : "Add a sign-in provider"}
    >
      <form onSubmit={submit} className="flex flex-col gap-4">
        {!editing && (
          <SelectField
            label="Provider"
            value={kind}
            onChange={(event) => {
              const next = event.target.value as SsoKindValue;
              setKind(next);
              const info = (kinds.data ?? []).find((k) => k.kind === next);
              if (!name.trim() && info) setName(info.name);
            }}
          >
            {(kinds.data ?? []).map((info) => (
              <option key={info.kind} value={info.kind}>
                {info.name}
                {info.kind === SsoKind.oidc ? " / other OIDC issuer" : ""}
              </option>
            ))}
          </SelectField>
        )}

        <TextField
          label="Button label"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={kindInfo?.name ?? "Google"}
          hint="What the sign-in button says."
        />

        {!isGoogle && (
          <TextField
            label="Issuer URL"
            value={issuer}
            onChange={(event) => setIssuer(event.target.value)}
            placeholder="https://id.example.com"
            hint="The base URL that serves /.well-known/openid-configuration."
            required
          />
        )}

        <TextField
          label="Client ID"
          value={clientId}
          onChange={(event) => setClientId(event.target.value)}
          autoComplete="off"
          required
        />
        <TextField
          label="Client secret"
          type="password"
          value={clientSecret}
          onChange={(event) => setClientSecret(event.target.value)}
          autoComplete="new-password"
          placeholder={existing?.has_client_secret ? "•••••••• (stored)" : ""}
          hint={
            existing?.has_client_secret
              ? "Leave blank to keep the stored secret."
              : undefined
          }
          required={!editing}
        />

        {existing?.redirect_uri && <RedirectUriField uri={existing.redirect_uri} />}

        <div className="border-t border-subtle pt-4">
          <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
            Who may sign up
          </div>
          <div className="flex flex-col gap-3">
            <CheckboxField
              label="Allow new accounts from this provider"
              help="Off: only people who already have a Radd account can sign in here."
              checked={autoProvision}
              onChange={setAutoProvision}
            />
            <div>
              <div className="mb-1 text-[13px] text-fg">Allowed sign-up domains</div>
              <TokenMultiSelect
                value={domains}
                onChange={setDomains}
                options={[]}
                allowCreate
                disabled={!autoProvision}
                placeholder="radd-hq.com"
                createLabel={(term) => `Allow ${term.replace(/^@/, "")}`}
                ariaLabel="Allowed sign-up domains"
              />
              <p className="mt-1 text-xs text-fg-muted">
                {!autoProvision
                  ? "New accounts are off, so the list doesn't apply."
                  : wildcard
                    ? "“*” lets anyone the provider authenticates create an account."
                    : domains.length === 0
                      ? "Empty means NO new accounts — nobody can sign up through this provider."
                      : "Only these domains can create an account. People who already have one sign in from any domain."}
              </p>
            </div>
            <CheckboxField
              label="Require a verified email address"
              help="Recommended. An unverified address must never be trusted — matching one to an existing account is how a stranger would take it over."
              checked={requireVerified}
              onChange={setRequireVerified}
            />
          </div>
        </div>

        <div className="border-t border-subtle pt-4">
          <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
            Admin group sync (optional)
          </div>
          <div className="flex flex-col gap-3">
            <TextField
              label="Groups claim"
              value={groupClaim}
              onChange={(event) => setGroupClaim(event.target.value)}
              placeholder="groups"
            />
            <SelectField
              label="Role for new accounts"
              value={defaultRoleId}
              onChange={(event) => setDefaultRoleId(event.target.value)}
              hint="Granted once, when this provider CREATES an account — never re-applied. Revoke it or change it later and no future sign-in will put it back, which is the difference between a starting point and a policy the provider keeps enforcing."
            >
              <option value="">No role — start on the Baseline only</option>
              {(roles.data ?? [])
                .filter((role) => role.key !== BASELINE_ROLE_KEY)
                .map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.name}
                  </option>
                ))}
            </SelectField>
            <TextField
              label="Admin groups"
              value={adminGroups}
              onChange={(event) => setAdminGroups(event.target.value)}
              placeholder="radd-admins, platform"
              hint="Comma-separated. Members become instance admins, re-synced on every login. LEAVE BLANK unless this provider really carries group data — a blank list means the provider has no opinion and leaves roles alone, which is what stops it demoting an admin whose account it links to."
            />
          </div>
        </div>

        <CheckboxField
          label="Enabled"
          help="Off: the button disappears from the login page."
          checked={enabled}
          onChange={setEnabled}
        />

        {error && <p className="text-xs text-red-400">{error}</p>}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : editing ? "Save" : "Add provider"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
