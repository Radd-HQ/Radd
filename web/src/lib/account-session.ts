import type { QueryClient } from "@tanstack/react-query";
import { abortAccountRequests } from "./api";
import { stopAllRealtime } from "./realtime";
import { setStorageAccount } from "./account-storage";

/** Tear down the old identity before a full navigation drops component drafts. */
export async function resetAccountSession(client: QueryClient) {
  stopAllRealtime();
  abortAccountRequests();
  await client.cancelQueries();
  client.clear();
  setStorageAccount(null);
}
