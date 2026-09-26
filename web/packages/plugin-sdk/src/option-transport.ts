import { api } from "./api";
import type { DirectoryOption, OptionSource } from "./options";

/** The transport of an owner's standard options endpoint: pages by `q`/`limit`/`offset`, resolves
 *  one saved value by `value`, and sends the control's scope along as query parameters. The owner
 *  names the path; the controls in `options.tsx` stay transport-free. */
export function optionTransport(path: string): Pick<OptionSource, "fetch" | "resolve"> {
  return {
    fetch: ({ q, limit, offset, scope, signal }) =>
      api.getPaged<DirectoryOption>(path, { signal, query: { ...scope, q, limit: String(limit), offset: String(offset) } }),
    resolve: ({ value, scope, signal }) =>
      api.get<DirectoryOption[]>(path, { signal, query: { ...scope, value, limit: "1" } }),
  };
}
