import { DirectorySelect, type DirectoryChoice } from "@radd/plugin-sdk";

/** Compatibility adapter for existing feature callers. Auth/Teams contribute the control,
 * own its queries and enforce candidate semantics. New plugin callers use DirectorySelect. */
export function PeopleDirectorySelect({ kind, candidateTeamId, candidatePurpose, ...props }: {
  kind: "person" | "team"; value: DirectoryChoice | null; candidateTeamId?: string;
  candidatePurpose?: "member" | "manager" | "owner"; disabled?: boolean;
  onChange: (value: DirectoryChoice | null) => void; label: string; emptyLabel: string;
}) {
  return <DirectorySelect {...props}
    source={candidateTeamId ? "teams.candidates" : kind === "person" ? "auth.people" : "teams.teams"}
    context={{ teamId: candidateTeamId, purpose: candidatePurpose }} />;
}
