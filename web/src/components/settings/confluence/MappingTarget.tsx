import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { pageSpacesQuery, pageExtensionsQuery, groupsQuery } from "../../../lib/queries";
import type { ConfluenceMappingSection } from "../../../lib/types";
import { SelectField } from "../../SelectField";
import { PeopleDirectorySelect } from "../../PeopleDirectorySelect";
import { QueryError } from "../../QueryError";

/** Render destinations only for operations supported by the importer. */
export function MappingTarget({ section, row, onChange }: {
  section: ConfluenceMappingSection; row: Record<string, unknown>;
  onChange: (changes: Record<string, unknown>) => void;
}) {
  const spaces = useQuery({ ...pageSpacesQuery(), enabled: section === "spaces" && row.action === "map" });
  const extensions = useQuery({ ...pageExtensionsQuery, enabled: section === "macros" && row.action === "extension" });
  const groups = useQuery({ ...groupsQuery(), enabled: section === "groups" && row.action === "map" });
  const [subjectKind, setSubjectKind] = useState(row.team_id ? "team" : "group");
  const [names, setNames] = useState<Record<string, string>>({});
  const text = (key: string, label: string) => <label className="flex flex-col gap-1">{label}<input className="h-8 rounded border border-strong bg-surface px-2" value={String(row[key] ?? "")} onChange={e => onChange({ [key]: e.target.value })}/></label>;
  const picker = (key: string, label: string, choices: {id: string; name: string}[], empty = "Choose a destination…") => <SelectField label={label} value={String(row[key] ?? "")} onChange={e => onChange({[key]: e.target.value || null})}>
    <option value="">{empty}</option>
    {row[key] && !choices.some(c => c.id === row[key]) ? <option value={String(row[key])} disabled>Unavailable destination ({String(row[key])})</option> : null}
    {choices.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
  </SelectField>;
  if (row.action === "ignore" || row.action === "fail") return null;
  if (section === "spaces") return row.action === "create" ? text("target_name", "New space name") : <>{spaces.isError && <QueryError label="spaces" error={spaces.error}/>} {picker("space_id", "Existing space", spaces.data ?? [])}</>;
  if (section === "users") return <div><p className="mb-1">Attribution account</p><PeopleDirectorySelect kind="person" label="Choose attribution account" emptyLabel="Automatic account matching" value={row.user_id ? {id: String(row.user_id),name:names[String(row.user_id)] ?? `Selected account (${row.user_id})`} : null} onChange={choice => { if(choice) setNames(n => ({...n,[choice.id]:choice.name})); onChange({user_id:choice?.id ?? null}); }}/><p className="mt-1 text-xs text-fg-muted">Applies to authors and mentions; page access restrictions are resolved separately.</p></div>;
  if (section === "macros" && row.action === "extension") return <>{extensions.isError && <QueryError label="page renderers" error={extensions.error}/>} {picker("extension", "Page renderer", (extensions.data ?? []).map(e => ({id:e.name,name:e.label})))}</>;
  if (section === "groups" && row.action === "map") return <div className="space-y-2">
    <SelectField label="Permission destination" value={subjectKind} onChange={e => {setSubjectKind(e.target.value);onChange({group_id:null,team_id:null});}}><option value="group">Directory group</option><option value="team">Feature team</option></SelectField>
    {groups.isError && <QueryError label="groups" error={groups.error}/>}
    {subjectKind === "team" ? <PeopleDirectorySelect kind="team" label="Choose permission team" emptyLabel="Choose a team…" value={row.team_id ? {id:String(row.team_id),name:names[String(row.team_id)] ?? String(row.team_id)} : null} onChange={c => {if(c)setNames(n => ({...n,[c.id]:c.name}));onChange({team_id:c?.id ?? null,group_id:null});}}/> : picker("group_id", "Directory group", groups.data ?? [])}
  </div>;
  return null;
}
