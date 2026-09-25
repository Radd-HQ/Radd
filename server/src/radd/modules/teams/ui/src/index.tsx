import { TeamSelect as RelationshipSelect, TeamChoices } from "./RelationshipSelect";
import { TeamAudience } from "./TeamAudience";
import { TEAM_SELECT_SLOT, TEAM_CHOICES_SLOT, TEAM_AUDIENCE_SLOT, type TeamSelectProps, type TeamChoicesProps, type TeamAudienceProps } from "./relationship-contract";
import { optionContributions } from "./options";
import { definePlugin, DIRECTORY_SELECT_SLOT, PagedDirectorySelect, api, type DirectoryChoice, type DirectorySelectProps } from "@radd/plugin-sdk";

function TeamSelect(props: DirectorySelectProps) {
  return <PagedDirectorySelect {...props} noun="teams" searchPlaceholder="Search teams…" query={(q, page, pageSize) => ({
    queryKey: ["teams", "choices", q, page, ""],
    meta: { entities: ["team", "role"] },
    queryFn: ({ signal }) => api.getPaged<DirectoryChoice>("/teams", { signal, query: { q, limit: String(pageSize), offset: String(page * pageSize) } }),
  })} />;
}

function CandidateSelect(props: DirectorySelectProps) {
  const teamId = props.context?.teamId;
  const purpose = props.context?.purpose ?? "member";
  if (!teamId || !["member", "manager", "owner"].includes(purpose)) return <span role="alert">A valid team and candidate purpose are required.</span>;
  return <PagedDirectorySelect {...props} noun="people" searchPlaceholder="Search people…" clearLabel="Clear selection" query={(q, page, pageSize) => ({
    queryKey: ["teamMembers", { teamId }, "choices", q, page, purpose],
    meta: { entities: ["member", "team", "role"] },
    queryFn: ({ signal }) => api.getPaged<DirectoryChoice>(`/teams/${encodeURIComponent(teamId)}/${purpose === "member" ? "member-candidates" : "steward-candidates"}`, {
      signal, query: { q, limit: String(pageSize), offset: String(page * pageSize), ...(purpose === "member" ? {} : { purpose }) },
    }),
  })} />;
}

export default definePlugin({ contributions: [...optionContributions,
  { id: "relationship-select", slot: TEAM_SELECT_SLOT, toggleable: false, render: props => <RelationshipSelect {...(props as unknown as TeamSelectProps)} /> },
  { id: "relationship-choices", slot: TEAM_CHOICES_SLOT, toggleable: false, render: props => <TeamChoices {...(props as unknown as TeamChoicesProps)} /> },
  { id: "relationship-audience", slot: TEAM_AUDIENCE_SLOT, toggleable: false, render: props => <TeamAudience {...(props as unknown as TeamAudienceProps)} /> },
  { id: "team-select", slot: DIRECTORY_SELECT_SLOT, match: "teams.teams", toggleable: false, render: props => <TeamSelect {...(props as unknown as DirectorySelectProps)} /> },
  { id: "candidate-select", slot: DIRECTORY_SELECT_SLOT, match: "teams.candidates", toggleable: false, render: props => <CandidateSelect {...(props as unknown as DirectorySelectProps)} /> },
] });
