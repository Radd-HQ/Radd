import { SelectField } from "@radd/plugin-sdk";
import { MappingTarget } from "./MappingTarget";
import { ConfluenceMacroAction, type ConfluenceMappingSection } from "./types";

/** One mapping table: a row per thing counted in the download, and what becomes of it. */
export function MappingRows({
  section,
  rows,
  highlight,
  onChange,
}: {
  section: ConfluenceMappingSection;
  rows: Record<string, unknown>[];
  highlight: string;
  onChange: (index: number, changes: Record<string, unknown>) => void;
}) {
  if (!rows.length) {
    return <p className="text-[13px] text-fg-faint">Nothing of this kind in the download.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-subtle text-left text-[12px] text-fg-muted">
            <th className="py-1.5 pr-3 font-medium">Name</th>
            <th className="py-1.5 pr-3 font-medium">Used</th>
            <th className="py-1.5 pr-3 font-medium">What happens</th>
            <th className="py-1.5 font-medium">Destination</th>
            <th className="py-1.5 font-medium">Why</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const name = String(row.name ?? row.key ?? row.username ?? row.project_key ?? "");
            return (
              <tr
                key={name}
                className={`border-b border-subtle last:border-0 ${
                  highlight && Object.values(row).includes(highlight) ? "bg-elevated" : ""
                }`}
              >
                <td className="py-1.5 pr-3 font-mono text-[12px] text-fg">{name}</td>
                <td className="py-1.5 pr-3 text-fg-muted">{String(row.count ?? 0)}</td>
                <td className="py-1.5 pr-3">
                  <ActionSelect
                    section={section}
                    value={String(row.action ?? "")}
                    onChange={(action) => onChange(index, { action })}
                  />
                </td>
                <td className="p-2"><MappingTarget section={section} row={row} onChange={changes => onChange(index, changes)}/></td>
                <td className="py-1.5 text-[12px] text-fg-muted">
                  {String(row.reason ?? row.sample_page ?? "")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const ACTIONS: Record<ConfluenceMappingSection, { value: string; label: string }[]> = {
  spaces: [
    { value: "create", label: "Create a space" },
    { value: "map", label: "Use existing space" },
    { value: "ignore", label: "Skip" },
  ],
  macros: [
    { value: ConfluenceMacroAction.extension, label: "Render as a block" },
    { value: ConfluenceMacroAction.native, label: "Plain markdown" },
    { value: ConfluenceMacroAction.unsupported, label: "Keep as a card" },
    { value: ConfluenceMacroAction.strip, label: "Remove" },
  ],
  users: [
    { value: "map", label: "Match an account" },
    { value: "ignore", label: "Leave unattributed" },
  ],
  groups: [
    { value: "identity", label: "Same group" },
    { value: "map", label: "Choose group or team" },
    { value: "fail", label: "Refuse the page" },
  ],
  labels: [
    { value: "create", label: "Create the label" },
    { value: "ignore", label: "Skip" },
  ],
  jira_links: [
    { value: "resolve", label: "Link to the issue here" },
    { value: "external", label: "Link to Jira" },
    { value: "ignore", label: "Plain text" },
  ],
};

function ActionSelect({
  section,
  value,
  onChange,
}: {
  section: ConfluenceMappingSection;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <SelectField
      label="Action"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="min-w-40"
    >
      {ACTIONS[section].map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </SelectField>
  );
}
