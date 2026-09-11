import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { BUILTIN_FIELD_LABELS } from "../../lib/meta";
import {
  BUILTIN_RULE_FIELDS,
  GrantSubject,
  WRITE_ONLY_BUILTIN_FIELDS,
  type BuiltinRuleField,
} from "../../lib/types";
import { FieldProjectChoices } from "./FieldProjectScope";
import { Button } from "../Button";
import { AccessGrantsEditor, type ResourceGrantScope } from "./AccessGrantsEditor";
import { settingsTableClasses } from "./SettingsPage";

/**
 * Access grants for the BUILTIN item fields (spec 36 write, spec 50 read → spec 92).
 * Each field is a resource in the generic access framework (`builtin_field`), so it
 * uses the same reusable AccessGrantsEditor as custom fields — subject picker,
 * read/write, and per-grant project scope. Structural rows (title/state/priority)
 * are write-only (can't be blanked).
 */
export function BuiltinFieldsSection({ canManage, canManageProjects = false }: { canManage: boolean; canManageProjects?: boolean }) {
  const [expanded, setExpanded] = useState<BuiltinRuleField | null>(null);

  const [scope, setScope] = useState<ResourceGrantScope>();
  const [choosingProject, setChoosingProject] = useState(false);
  const scopeReady = canManage || scope !== undefined;

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

      {!canManage && !canManageProjects ? (
        <p className="text-sm text-fg-muted">Managing builtin-field access needs field.manage.</p>
      ) : <>
        <div className="mb-3 flex flex-wrap items-center gap-2" aria-label="Builtin grant scope">
          {canManage && <>
            <Button size="sm" variant="secondary" aria-pressed={scope === undefined} onClick={() => setScope(undefined)}>All scopes</Button>
            <Button size="sm" variant="secondary" aria-pressed={scope?.id === null} onClick={() => setScope({ id: null, label: "Global" })}>Global only</Button>
          </>}
          {canManageProjects && <Button size="sm" variant="secondary" onClick={() => setChoosingProject(true)}>Choose project</Button>}
          {scope?.id && <span className="text-xs text-fg-muted">Project: <strong>{scope.label}</strong></span>}
        </div>
        {scope && <p className="mb-3 text-xs text-fg-muted">Showing grants saved in {scope.label}. {scope.id ? "Global grants may also apply; changing them requires global field management." : "Project-specific grants are shown in their own scope."}</p>}
        {!scopeReady ? <p className="text-sm text-fg-muted">Choose a project to manage its builtin-field grants.</p> : <div className="overflow-x-auto rounded-lg border border-subtle">
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
                            key={`${field}:${scope === undefined ? "all" : scope.id ?? "global"}`}
                            scope={scope}
                            projectPermission="field.manage"
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
        </div>}
        {choosingProject && <FieldProjectChoices permission="field.manage" selected={scope?.id ? [scope.id] : []}
          onClose={() => setChoosingProject(false)} onSelect={(id, label) => { setScope({ id, label }); setChoosingProject(false); }} />}
      </>}
    </section>
  );
}
