import { useContributedQuery, type AvatarUser } from "@radd/plugin-sdk";

/** The people directory auth contributes — for author names and avatars. A visitor has none. */
export function usePeople(enabled = true): AvatarUser[] | undefined {
  return useContributedQuery<AvatarUser[]>("auth.people", {}, { enabled }).data;
}
