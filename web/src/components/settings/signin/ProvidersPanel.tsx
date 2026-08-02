import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, KeyRound, Pencil, Plus, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../../lib/api";
import { apiSsoProviderPath, apiSsoProviderTestPath } from "../../../lib/constants";
import { instanceStatusQuery, queryKeys, ssoProvidersQuery } from "../../../lib/queries";
import {
  SIGNUP_DOMAIN_WILDCARD,
  SsoKind,
  type SsoProbeResult,
  type SsoProviderRead,
} from "../../../lib/types";
import { Button } from "../../Button";
import { useConfirm } from "../../ConfirmDialog";
import { EmptyState } from "../../EmptyState";
import { QueryError } from "../../QueryError";
import { Table, TBody, Td, Th, THead } from "../../Table";
import { TableSkeleton } from "../../TableSkeleton";
import { ProviderDialog } from "./ProviderDialog";

/** Who may create an account here, as one readable phrase. */
function SignupSummary({ provider }: { provider: SsoProviderRead }) {
  if (!provider.auto_provision) {
    return <span className="text-fg-muted">Existing accounts only</span>;
  }
  if (provider.allowed_signup_domains.includes(SIGNUP_DOMAIN_WILDCARD)) {
    return <span className="text-amber-400">Anyone (*)</span>;
  }
  if (provider.allowed_signup_domains.length === 0) {
    return <span className="text-fg-muted">No sign-ups</span>;
  }
  return (
    <span className="flex flex-wrap gap-1">
      {provider.allowed_signup_domains.map((domain) => (
        <span
          key={domain}
          className="rounded-md border border-subtle bg-base px-1.5 py-0.5 text-xs text-fg-secondary"
        >
          {domain}
        </span>
      ))}
    </span>
  );
}

function StatusChip({ provider }: { provider: SsoProviderRead }) {
  if (!provider.configured) {
    return (
      <span
        className="rounded-md border border-amber-500/40 px-1.5 py-0.5 text-xs text-amber-400"
        title="Add a client ID and secret before this appears on the login page."
      >
        Incomplete
      </span>
    );
  }
  if (!provider.enabled) {
    return (
      <span className="rounded-md border border-subtle px-1.5 py-0.5 text-xs text-fg-muted">
        Disabled
      </span>
    );
  }
  return (
    <span className="rounded-md border border-emerald-500/40 px-1.5 py-0.5 text-xs text-emerald-400">
      On login page
    </span>
  );
}

/**
 * The sign-in provider registry (spec 110): every identity provider the login
 * page can offer, and the signup policy each one carries.
 */
export function ProvidersPanel() {
  const providers = useQuery(ssoProvidersQuery());
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const [editing, setEditing] = useState<SsoProviderRead | null>(null);
  const [adding, setAdding] = useState(false);
  const [checks, setChecks] = useState<Record<string, SsoProbeResult | "pending">>({});

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.ssoProviders });
    void queryClient.invalidateQueries({ queryKey: instanceStatusQuery.queryKey });
  };

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(apiSsoProviderPath(id)),
    onSuccess: invalidate,
  });

  const test = async (provider: SsoProviderRead) => {
    setChecks((prev) => ({ ...prev, [provider.id]: "pending" }));
    try {
      const result = await api.post<SsoProbeResult>(apiSsoProviderTestPath(provider.id), {});
      setChecks((prev) => ({ ...prev, [provider.id]: result }));
    } catch (err) {
      setChecks((prev) => ({
        ...prev,
        [provider.id]: { ok: false, error: errorMessage(err), authorization_endpoint: "" },
      }));
    }
  };

  const onDelete = async (provider: SsoProviderRead) => {
    const ok = await confirm({
      title: `Remove ${provider.name}?`,
      message:
        "People who signed in through this provider lose that route in. Their accounts, and " +
        "any other way they sign in, are untouched.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (ok) remove.mutate(provider.id);
  };

  if (providers.isError) return <QueryError label="sign-in providers" error={providers.error} />;

  const rows = providers.data ?? [];

  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-[11px] font-medium uppercase tracking-wide text-fg-muted">
          Providers
        </h2>
        <Button size="sm" variant="ghost" onClick={() => setAdding(true)}>
          <Plus className="size-3.5" />
          Add provider
        </Button>
      </div>

      {providers.isLoading ? (
        <TableSkeleton rows={2} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={KeyRound}
          message="No sign-in providers yet — add Google to let people sign in with their work account."
          action={
            <Button size="sm" onClick={() => setAdding(true)}>
              <Plus className="size-3.5" />
              Add provider
            </Button>
          }
        />
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>Provider</Th>
              <Th>Status</Th>
              <Th>Who may sign up</Th>
              <Th>Roles</Th>
              <Th className="w-px" />
            </tr>
          </THead>
          <TBody>
            {rows.map((provider) => {
              const check = checks[provider.id];
              return (
                <tr key={provider.id}>
                  <Td>
                    <div className="font-medium text-fg">{provider.name}</div>
                    {/* The issuer, not the kind — a row labelled "Google / Google"
                        says nothing twice. */}
                    <div className="text-xs text-fg-muted">
                      {provider.kind === SsoKind.google
                        ? "accounts.google.com"
                        : provider.issuer || "OIDC"}
                    </div>
                    {check && check !== "pending" && (
                      <div
                        className={`mt-1 text-xs ${check.ok ? "text-emerald-400" : "text-red-400"}`}
                      >
                        {check.ok ? "Issuer reachable" : check.error}
                      </div>
                    )}
                    {check === "pending" && (
                      <div className="mt-1 text-xs text-fg-muted">Checking…</div>
                    )}
                  </Td>
                  <Td>
                    <StatusChip provider={provider} />
                  </Td>
                  <Td>
                    <SignupSummary provider={provider} />
                  </Td>
                  <Td>
                    {provider.admin_groups.trim() ? (
                      <span className="text-xs text-fg-secondary">
                        Synced from {provider.group_claim}
                      </span>
                    ) : (
                      <span className="text-xs text-fg-muted">Left alone</span>
                    )}
                  </Td>
                  <Td>
                    <div className="flex justify-end gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => void test(provider)}
                        title="Fetch the issuer's discovery document"
                      >
                        <Activity className="size-3.5" />
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(provider)}>
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => void onDelete(provider)}
                        title="Remove"
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  </Td>
                </tr>
              );
            })}
          </TBody>
        </Table>
      )}

      {(adding || editing) && (
        <ProviderDialog
          existing={editing}
          onClose={() => {
            setAdding(false);
            setEditing(null);
          }}
        />
      )}
      {confirmDialog}
    </section>
  );
}
