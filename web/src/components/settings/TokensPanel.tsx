import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound, Plus, TriangleAlert, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, apiTokenPath } from "../../lib/constants";
import { formatDateOrNever } from "../../lib/dates";
import { usePermissions } from "../../lib/hooks";
import { queryKeys, tokensQuery } from "../../lib/queries";
import type { ApiToken, ApiTokenCreate, ApiTokenCreated, TokenScopes } from "../../lib/types";
import { Button } from "../Button";
import { Callout } from "../Callout";
import { EmptyState } from "../EmptyState";
import { ErrorText } from "../ErrorText";
import { TableSkeleton } from "../TableSkeleton";
import { TextField } from "../TextField";
import { SettingsPage, settingsTableClasses } from "./SettingsPage";
import { TokenScopeEditor, TokenScopeSummary, scopeIsIncomplete } from "./TokenScopeEditor";

/**
 * Personal access tokens: create (secret shown once), list, revoke. Shared by
 * the API-tokens settings page and the Profile page (spec 34).
 */
export function TokensPanel() {
  const tokens = useQuery(tokensQuery);
  const [created, setCreated] = useState<ApiTokenCreated | null>(null);
  const list = tokens.data ?? [];

  return (
    <>
      {created && <CreatedTokenPanel created={created} onDismiss={() => setCreated(null)} />}

      {tokens.isPending ? (
        <TableSkeleton rows={3} />
      ) : tokens.isError ? (
        <p className="text-sm text-red-400">Failed to load tokens: {errorMessage(tokens.error)}</p>
      ) : list.length === 0 ? (
        <EmptyState icon={KeyRound} message="No tokens yet — create one below." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <table className={settingsTableClasses.table}>
            <thead>
              <tr>
                <th className={settingsTableClasses.head}>Name</th>
                <th className={settingsTableClasses.head}>Token</th>
                <th className={settingsTableClasses.head}>Scope</th>
                <th className={settingsTableClasses.head}>Created</th>
                <th className={settingsTableClasses.head}>Expires</th>
                <th className={settingsTableClasses.head}>Last used</th>
                <th className={settingsTableClasses.head}>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.map((token) => (
                <TokenRow key={token.id} token={token} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <NewTokenForm onCreated={setCreated} />
    </>
  );
}

/** The API-tokens settings route body — the ONE home for personal tokens (RADD-1095). */
export function TokensSettingsBody() {
  return (
    <SettingsPage
      title="API tokens"
      description="Personal access tokens for scripts and integrations — sent as `Authorization: Bearer radd_pat_…`. They act with your permissions."
    >
      <TokensPanel />
    </SettingsPage>
  );
}

/** The one moment the full secret exists client-side — copy it or lose it. */
function CreatedTokenPanel({
  created,
  onDismiss,
}: {
  created: ApiTokenCreated;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(created.token);
      setCopied(true);
    } catch {
      // Clipboard unavailable (permissions/insecure context) — the token stays
      // visible in the <code> block for manual selection.
    }
  };

  return (
    <Callout kind="warning" icon={null} className="mb-5 rounded-lg p-4">
      <div className="mb-2 flex items-center gap-2 text-[13px] font-medium">
        <TriangleAlert size={15} aria-hidden />
        Copy “{created.name}” now — this token won't be shown again.
      </div>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded-md border border-strong bg-base px-3 py-2 font-mono text-xs text-heading">
          {created.token}
        </code>
        <Button variant="ghost" onClick={() => void copy()}>
          {copied ? (
            <>
              <Check size={14} className="text-emerald-400" aria-hidden />
              Copied
            </>
          ) : (
            <>
              <Copy size={14} aria-hidden />
              Copy
            </>
          )}
        </Button>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss new token"
          className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
        >
          <X size={15} />
        </button>
      </div>
    </Callout>
  );
}

/** Token row with a two-step inline revoke (no browser confirm dialog). */
function TokenRow({ token }: { token: ApiToken }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  const revoke = useMutation({
    mutationFn: () => api.delete<void>(apiTokenPath(token.id)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.tokens }),
  });

  return (
    <tr className="last:[&>td]:border-b-0">
      <td className={`${settingsTableClasses.cell} text-heading`}>{token.name}</td>
      <td className={`${settingsTableClasses.cell} font-mono text-xs text-fg-secondary`}>
        {token.prefix_display}…
      </td>
      <td className={settingsTableClasses.cell}>
        <TokenScopeSummary scopes={token.scopes} />
      </td>
      <td className={settingsTableClasses.cell}>{formatDateOrNever(token.created_at)}</td>
      <td className={settingsTableClasses.cell}>{formatDateOrNever(token.expires_at)}</td>
      <td className={settingsTableClasses.cell}>{formatDateOrNever(token.last_used_at)}</td>
      <td className={`${settingsTableClasses.cell} text-right`}>
        {confirming ? (
          <span className="inline-flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => revoke.mutate()}
              disabled={revoke.isPending}
              className="rounded px-1.5 py-0.5 text-xs font-medium text-red-400 hover:bg-red-500/10 cursor-pointer disabled:opacity-50"
            >
              {revoke.isPending ? "Revoking…" : "Confirm revoke"}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded px-1.5 py-0.5 text-xs text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
            >
              Keep
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="rounded px-1.5 py-0.5 text-xs text-fg-muted hover:bg-elevated hover:text-red-400 cursor-pointer"
          >
            Revoke
          </button>
        )}
        {revoke.isError && (
          <span className="ml-2 text-xs text-red-400">{errorMessage(revoke.error)}</span>
        )}
      </td>
    </tr>
  );
}

function NewTokenForm({ onCreated }: { onCreated: (token: ApiTokenCreated) => void }) {
  const queryClient = useQueryClient();
  const perms = usePermissions();
  const [name, setName] = useState("");
  const [expiresOn, setExpiresOn] = useState("");
  // null = the owner's full authority — what every personal token was until
  // RADD-1009 let the browser narrow one (spec 113 shape, server-intersected).
  const [scopes, setScopes] = useState<TokenScopes | null>(null);

  const createToken = useMutation({
    mutationFn: (body: ApiTokenCreate) => api.post<ApiTokenCreated>(ApiPath.tokens, body),
    onSuccess: async (token) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.tokens });
      setName("");
      setExpiresOn("");
      setScopes(null);
      onCreated(token);
    },
  });

  const incomplete = scopeIsIncomplete(scopes);
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || incomplete) return;
    createToken.mutate({
      name: name.trim(),
      // Date-only input → expire at the end of that day (UTC).
      expires_at: expiresOn ? `${expiresOn}T23:59:59Z` : null,
      scopes,
    });
  };

  return (
    <form onSubmit={onSubmit} className="mt-4 flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-48 flex-1">
          <TextField
            label="New token"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="ci-importer"
            maxLength={200}
          />
        </div>
        <TextField
          label="Expires (optional)"
          type="date"
          value={expiresOn}
          onChange={(event) => setExpiresOn(event.target.value)}
        />
        <Button type="submit" disabled={createToken.isPending || !name.trim() || incomplete}>
          <Plus size={14} aria-hidden />
          {createToken.isPending ? "Creating…" : "Create token"}
        </Button>
      </div>
      {/* Only atoms the owner holds somewhere are offered: a key can never
          exceed its account, so offering the rest would be a lie the server
          silently corrects. An instance admin sees the whole catalog. */}
      <TokenScopeEditor
        value={scopes}
        onChange={setScopes}
        allowedAtoms={(atom) => perms.anyProject(atom)}
        disabled={createToken.isPending}
      />
      {createToken.isError && <ErrorText error={createToken.error} />}
    </form>
  );
}
