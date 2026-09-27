import type { Label } from "@radd-plugin-ui/labels/types";
import type { FieldDef } from "@radd-plugin-ui/fields/types";
import { useContributedQuery } from "@radd/plugin-sdk";
import { usePermissions } from "@radd/plugin-sdk";

/** Picker options gathered once for every action row (spec 20 actions builder). */
export interface PickerData {
  canChoosePeople: boolean;
  labelNames: string[];
  fields: FieldDef[];
  catalogStatus: { name: string; available: boolean; loading: boolean; error: unknown; retry: () => void }[];
}

function catalogStatus(name: string, query: { available: boolean; isPending: boolean; error: unknown; refetch: () => unknown }) {
  return { name, available: query.available, loading: query.available && query.isPending, error: query.error,
    retry: () => { void query.refetch(); } };
}

const uniqueSorted = (values: string[]) => [...new Set(values)].sort((a, b) => a.localeCompare(b));

/** Remaining global registries; project-owned choices load in their controls. */
export function usePickerData(): PickerData {
  const perms = usePermissions();
  const labels = useContributedQuery<Label[]>("labels.catalog");
  const fields = useContributedQuery<FieldDef[]>("fields.catalog");
  return {
    canChoosePeople: perms.global("user.manage"),
    labelNames: uniqueSorted((labels.data ?? []).map((label) => label.name)),
    fields: fields.data ?? [],
    catalogStatus: [catalogStatus("Fields", fields), catalogStatus("Labels", labels)],
  };
}
