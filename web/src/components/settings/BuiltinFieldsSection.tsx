import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { BUILTIN_FIELD_LABELS } from "../../lib/meta";
import {
  BUILTIN_RULE_FIELDS,
  GrantSubject,
  WRITE_ONLY_BUILTIN_FIELDS,
  type BuiltinRuleField,
} from "../../lib/types";
import { AccessGrantsEditor } from "./AccessGrantsEditor";
import { settingsTableClasses } from "./SettingsPage";

/**
 * Access grants for the BUILTIN item fields (spec 36 write, spec 50 read → spec 92).
 * Each field is a resource in the generic access framework (`builtin_field`), so it
 * uses the same reusable AccessGrantsEditor as custom fields — subject picker,
 * read/write, and per-grant project scope. Structural rows (title/state/priority)
 * are write-only (can't be blanked).
 */
export function BuiltinFieldsSection({ canManage }: { canManage: boolean }) {
  const [expanded, setExpanded] = useState<BuiltinRuleField | null>(null);

  return (
    <section aria-labelledby="builtin-fields-heading">
      <div className="mb-3">
        <h3 id="builtin-fields-heading" className="text-sm font-semibold text-heading">
          Builtin fields
        </h3>
        <p className="mt-1 text-[13px] text-fg-muted">
          Every item carries these. Expand a field to restrict who can change it — or, for most
          fields, who can see it — global or per project.
        </p>
      </div>

      {!canManage ? (
        <p className="text-sm text-fg-muted">Managing builtin-field access needs field.manage.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <table className={settingsTableClasses.table}>
            <thead>
              <tr>
                <th className={settingsTableClasses.head}>Field</th>
                <th className={settingsTableClasses.head} />
              </tr>
            </thead>
            <tbody>
              {BUILTIN_RULE_FIELDS.map((field) => {
                const open = expanded === field;
                const Chevron = open ? ChevronDown : ChevronRight;
                const writeOnly = WRITE_ONLY_BUILTIN_FIELDS.has(field);
                return (
                  <Fragment key={field}>
                    <tr className="last:[&>td]:border-b-0">
                      <td className={`${settingsTableClasses.cell} whitespace-nowrap text-heading`}>
                        {BUILTIN_FIELD_LABELS[field]}
                      </td>
                      <td className={`${settingsTableClasses.cell} whitespace-nowrap`}>
                        <button
                          type="button"
                          onClick={() => setExpanded((c) => (c === field ? null : field))}
                          aria-expanded={open}
                          className="inline-flex cursor-pointer items-center gap-1.5 rounded px-1 py-0.5 text-xs text-fg-muted hover:bg-elevated"
                        >
                          <Chevron size={13} aria-hidden />
                          {open ? "Hide" : "Grants"}
                        </button>
                      </td>
                    </tr>
                    {open && (
                      <tr>
                        <td colSpan={2} className="border-b border-subtle/60 bg-surface/40 px-3 py-3">
                          <AccessGrantsEditor
                            resourceType="builtin_field"
                            resourceId={field}
                            accesses={writeOnly ? ["write"] : ["read", "write"]}
                            subjectKinds={[GrantSubject.role, GrantSubject.team, GrantSubject.user]}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
