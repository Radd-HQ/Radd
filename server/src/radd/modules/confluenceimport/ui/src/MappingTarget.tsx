import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DirectorySelect, OptionSelect, QueryError, SelectField, TextField } from "@radd/plugin-sdk";
import { OptionResource, renderersQuery } from "./queries";
import type { ConfluenceMappingSection } from "./types";

/** The destination editor for one mapping row. Each destination belongs to another plugin and is
 * reached through its public surface (option directories, directory pickers, `pages`' API). */
export function MappingTarget({ section, row, onChange }: {
  section: ConfluenceMappingSection; row: Record<string, unknown>;
  onChange: (changes: Record<string, unknown>) => void;
}) {
  const renderers = useQuery({ ...renderersQuery(), enabled: section === "macros" && row.action === "extension" });
  const [subjectKind, setSubjectKind] = useState(row.team_id ? "team" : "group");
  const [names, setNames] = useState<Record<string, string>>({});
  const value = (key: string) => String(row[key] ?? "");
  if (row.action === "ignore" || row.action === "fail") return null;
  if (section === "spaces") {
    return row.action === "create"
      ? <TextField label="New space name" value={value("target_name")} onChange={e => onChange({ target_name: e.target.value })}/>
      : <OptionSelect resource={OptionResource.space} label="Existing space" value={value("space_id")} onChange={id => onChange({ space_id: id || null })}/>;
  }
  if (section === "users") return <div><p className="mb-1">Attribution account</p><DirectorySelect source="auth.people" label="Choose attribution account" emptyLabel="Automatic account matching" value={row.user_id ? {id: String(row.user_id),name:names[String(row.user_id)] ?? `Selected account (${row.user_id})`} : null} onChange={choice => { if(choice) setNames(n => ({...n,[choice.id]:choice.name})); onChange({user_id:choice?.id ?? null}); }}/><p className="mt-1 text-xs text-fg-muted">Applies to authors and mentions; page access restrictions are resolved separately.</p></div>;
  if (section === "macros" && row.action === "extension") {
    const choices = renderers.data ?? [];
    const current = value("extension");
    return <>
      {renderers.isError && <QueryError label="page renderers" error={renderers.error}/>}
      <SelectField label="Page renderer" value={current} onChange={e => onChange({ extension: e.target.value || null })}>
        <option value="">Choose a destination…</option>
        {current && !choices.some(c => c.name === current) ? <option value={current} disabled>Unavailable destination ({current})</option> : null}
        {choices.map(c => <option key={c.name} value={c.name}>{c.label}</option>)}
      </SelectField>
    </>;
  }
  if (section === "groups" && row.action === "map") return <div className="space-y-2">
    <SelectField label="Permission destination" value={subjectKind} onChange={e => {setSubjectKind(e.target.value);onChange({group_id:null,team_id:null});}}><option value="group">Directory group</option><option value="team">Feature team</option></SelectField>
    {subjectKind === "team"
      ? <DirectorySelect source="teams.teams" label="Choose permission team" emptyLabel="Choose a team…" value={row.team_id ? {id:String(row.team_id),name:names[String(row.team_id)] ?? String(row.team_id)} : null} onChange={c => {if(c)setNames(n => ({...n,[c.id]:c.name}));onChange({team_id:c?.id ?? null,group_id:null});}}/>
      : <OptionSelect resource={OptionResource.group} label="Directory group" value={value("group_id")} onChange={id => onChange({ group_id: id || null, team_id: null })}/>}
  </div>;
  return null;
}
