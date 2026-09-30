import { roleChange } from "./change-format";
import { optionContributions } from "./options";
import { peopleSource } from "./people";
import { ChangeLine, SlotId, type HistoryChange, definePlugin, DIRECTORY_SELECT_SLOT, PagedDirectorySelect, api, type DirectoryChoice, type DirectorySelectProps, Entity } from "@radd/plugin-sdk";

/** One `GET /users/directory` row, as far as the picker reads it. */
interface DirectoryPerson { id: string; name: string; active: boolean; source: string }

/** `UserSource.SERVICE` on the wire: the one source a picker must qualify, because a
 *  service account (the built-in Automation among them) is listed beside colleagues
 *  so that bylines resolve, and must never pass for one (RADD-869, RADD-1499). */
const SERVICE_SOURCE = "service";

function personChoice(person: DirectoryPerson): DirectoryChoice {
  const hint = person.source === SERVICE_SOURCE ? "Service account" : !person.active ? "Inactive" : undefined;
  return { id: person.id, name: person.name, hint };
}

/** Auth owns who can be selected from the people directory. */
function PersonSelect(props: DirectorySelectProps) {
  return <PagedDirectorySelect {...props} noun="people" searchPlaceholder="Search people…" query={(q, page, pageSize) => ({
    queryKey: ["users", "choices", q, page, ""],
    meta: { entities: [Entity.member, Entity.team, Entity.role] },
    queryFn: async ({ signal }) => {
      const page_ = await api.getPaged<DirectoryPerson>("/users/directory", {
        signal, query: { q, limit: String(pageSize), offset: String(page * pageSize) },
      });
      return { ...page_, rows: page_.rows.map(personChoice) };
    },
  })} />;
}

export default definePlugin({ querySources: [peopleSource], contributions: [...optionContributions,{
  id: "role-change-line", slot: SlotId.entityChangeLine, match: "role", toggleable: false,
  render: props => <ChangeLine change={roleChange(props.change as HistoryChange)} />,
},{
  id: "person-select", slot: DIRECTORY_SELECT_SLOT, match: "auth.people", toggleable: false,
  render: props => <PersonSelect {...(props as unknown as DirectorySelectProps)} />,
}] });
