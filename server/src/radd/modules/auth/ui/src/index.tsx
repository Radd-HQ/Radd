import { roleChange } from "./change-format";
import { optionContributions } from "./options";
import { peopleSource } from "./people";
import { ChangeLine, SlotId, type HistoryChange, definePlugin, DIRECTORY_SELECT_SLOT, PagedDirectorySelect, api, type DirectoryChoice, type DirectorySelectProps, Entity } from "@radd/plugin-sdk";

/** Auth owns who can be selected from the people directory. */
function PersonSelect(props: DirectorySelectProps) {
  return <PagedDirectorySelect {...props} noun="people" searchPlaceholder="Search people…" query={(q, page, pageSize) => ({
    queryKey: ["users", "choices", q, page, ""],
    meta: { entities: [Entity.member, Entity.team, Entity.role] },
    queryFn: ({ signal }) => api.getPaged<DirectoryChoice>("/users/directory", {
      signal, query: { q, limit: String(pageSize), offset: String(page * pageSize) },
    }),
  })} />;
}

export default definePlugin({ querySources: [peopleSource], contributions: [...optionContributions,{
  id: "role-change-line", slot: SlotId.entityChangeLine, match: "role", toggleable: false,
  render: props => <ChangeLine change={roleChange(props.change as HistoryChange)} />,
},{
  id: "person-select", slot: DIRECTORY_SELECT_SLOT, match: "auth.people", toggleable: false,
  render: props => <PersonSelect {...(props as unknown as DirectorySelectProps)} />,
}] });
