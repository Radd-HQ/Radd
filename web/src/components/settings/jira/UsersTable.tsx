import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, UserPlus } from "lucide-react";
import { usersQuery } from "../../../lib/queries";
import {
  USER_ACTION_LABELS,
  UserAction,
  type UserActionValue,
  type UserMapping,
} from "../../../lib/types";
import { Button } from "../../Button";
import { SelectField } from "../../SelectField";
import { TextField } from "../../TextField";
import { MappingSection } from "./MappingSection";

/**
 * What to do about every person Jira names (spec 100).
 *
 * Spec 90 had exactly ONE behaviour and no way to say otherwise: synthesize
 * `<jira username>@<a company domain hardcoded in the source>` and create the
 * account. Here each person is a row you decide — match an existing user, create
 * a placeholder at an address you can SEE first, attribute their work to someone
 * else, or leave it unattributed — with bulk actions for the long tail.
 *
 * Matched people collapse: if Radd already knows them there is nothing to decide.
 */
export function UsersTable({
  rows,
  domain,
  onChange,
  onBulk,
  onDomainChange,
}: {
  rows: UserMapping[];
  domain: string;
  onChange: (index: number, patch: Partial<UserMapping>) => void;
  onBulk: (patch: (row: UserMapping, index: number) => Partial<UserMapping> | null) => void;
  onDomainChange: (domain: string) => void;
}) {
  const users = useQuery(usersQuery);
  const [fallbackId, setFallbackId] = useState("");

  const unmatched = useMemo(
    () => rows.filter((r) => r.action !== UserAction.match),
    [rows],
  );
  const matched = useMemo(() => rows.filter((r) => r.action === UserAction.match), [rows]);
  const missingAddress = unmatched.filter(
    (r) => r.action === UserAction.placeholder && !r.placeholder_email,
  ).length;

  const row = (entry: UserMapping) => {
    const index = rows.indexOf(entry);
    return (
      <div key={entry.jira_key} className="flex flex-wrap items-center gap-2 px-3 py-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] text-fg">
            {entry.display_name || entry.jira_key}
            <span className="ml-1.5 text-xs text-fg-faint">
              {entry.jira_key} · {entry.count} reference{entry.count === 1 ? "" : "s"}
            </span>
          </p>
          <p className="truncate text-xs text-fg-muted">
            {entry.roles.join(", ") || "referenced"}
            {entry.match_reason && ` — ${entry.match_reason}`}
          </p>
        </div>
        <SelectField
          label=""
          ariaLabel={`${entry.display_name || entry.jira_key}: what to do`}
          className="w-44"
          value={entry.action}
          onChange={(e) => onChange(index, { action: e.target.value as UserActionValue })}
        >
          {Object.entries(USER_ACTION_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>
        {(entry.action === UserAction.match || entry.action === UserAction.fallback) && (
          <SelectField
            label=""
            ariaLabel={`${entry.display_name || entry.jira_key}: which Radd user`}
            className="w-56"
            value={entry.user_id ?? ""}
            onChange={(e) => onChange(index, { user_id: e.target.value || null })}
          >
            <option value="">Pick a user…</option>
            {(users.data ?? []).map((user) => (
              <option key={user.id} value={user.id}>
                {user.name} ({user.email})
              </option>
            ))}
          </SelectField>
        )}
        {entry.action === UserAction.placeholder && (
          <input
            aria-label={`${entry.display_name || entry.jira_key}: placeholder address`}
            value={entry.placeholder_email}
            placeholder="no address — set a domain, or map them instead"
            onChange={(e) => onChange(index, { placeholder_email: e.target.value })}
            className={
              "h-8 w-64 rounded-md border bg-surface px-2.5 text-[13px] text-heading outline-none " +
              "focus-visible:outline-2 focus-visible:outline-focus " +
              (entry.placeholder_email ? "border-strong" : "border-red-500/60")
            }
          />
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg border border-subtle bg-surface p-3">
        <div className="flex flex-wrap items-end gap-3">
          <TextField
            label="Placeholder email domain"
            value={domain}
            onChange={(e) => onDomainChange(e.target.value)}
            placeholder="derived from the Jira host"
            hint="Used only where Jira exposed no address. A later directory import matches on it and adopts the placeholder's work."
            className="w-64"
          />
        </div>
        {missingAddress > 0 && (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-amber-400">
            <CircleAlert size={13} />
            {missingAddress} {missingAddress === 1 ? "person has" : "people have"} no address —
            set a domain above, or map them to an existing user.
          </p>
        )}
      </div>

      {/* The long tail is the point of these: 300 unmatched people is normal. */}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            onBulk((r) =>
              r.action === UserAction.match ? null : { action: UserAction.placeholder },
            )
          }
        >
          <UserPlus size={13} /> Create placeholders for all unmatched
        </Button>
        <div className="flex items-center gap-1.5">
          <SelectField
            label=""
            ariaLabel="Attribute all unmatched people to this user"
            className="w-56"
            value={fallbackId}
            onChange={(e) => setFallbackId(e.target.value)}
          >
            <option value="">Attribute all unmatched to…</option>
            {(users.data ?? []).map((user) => (
              <option key={user.id} value={user.id}>
                {user.name}
              </option>
            ))}
          </SelectField>
          <Button
            size="sm"
            variant="secondary"
            disabled={!fallbackId}
            onClick={() =>
              onBulk((r) =>
                r.action === UserAction.match
                  ? null
                  : { action: UserAction.fallback, user_id: fallbackId },
              )
            }
          >
            Apply
          </Button>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={() =>
            onBulk((r) => (r.action === UserAction.match ? null : { action: UserAction.skip }))
          }
        >
          Leave all unmatched unattributed
        </Button>
      </div>

      <MappingSection
        title="Needs a decision"
        hint="Nobody in Radd matches these people."
        count={unmatched.length}
        defaultOpen
      >
        {unmatched.map(row)}
      </MappingSection>
      <MappingSection
        title="Already matched"
        hint="Radd already knows these people — nothing to decide."
        count={matched.length}
      >
        {matched.map(row)}
      </MappingSection>
      {rows.length === 0 && (
        <p className="flex items-center gap-1.5 text-xs text-fg-secondary">
          <CheckCircle2 size={13} className="text-emerald-400" />
          Nobody is referenced by these issues.
        </p>
      )}
    </div>
  );
}
