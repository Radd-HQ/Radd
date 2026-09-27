import { api, type AvatarUser, type QuerySource, Entity } from "@radd/plugin-sdk";

/** The people directory as data (RADD-1392): who a surface's authors and editors are, for names
 *  and avatars — the wiki's page header, history and discussion read it. Auth owns the transport. */
export const peopleSource: QuerySource<AvatarUser[]> = {
  key: "auth.people",
  meta: { entities: [Entity.member] },
  staleTime: 60_000,
  fetch: (_args, signal) => api.get<AvatarUser[]>("/users/directory", { signal }),
};
