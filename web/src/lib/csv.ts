import type { Item } from "./types";

/** RFC-4180-ish quoting: wrap when the value contains a comma/quote/newline. */
function cell(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

const HEADER = [
  "key",
  "title",
  "state",
  "category",
  "kind",
  "priority",
  "assignee",
  "reporter",
  "team",
  "labels",
  "cycle",
  "release",
  "start_date",
  "target_date",
  "created_at",
  "updated_at",
] as const;

/** Spec 32: flatten the fetched items to CSV (inherits the page cap). */
export function itemsToCsv(items: Item[]): string {
  const rows = items.map((item) =>
    [
      item.key,
      item.title,
      item.state.name,
      item.state.category,
      item.kind ?? "",
      item.priority,
      item.assignee?.name ?? "",
      item.reporter?.name ?? "",
      item.team?.name ?? "",
      (item.labels ?? []).join("; "),
      item.cycle?.name ?? "",
      item.release?.version ?? "",
      item.start_date ?? "",
      item.target_date ?? "",
      item.created_at,
      item.updated_at,
    ]
      .map(cell)
      .join(","),
  );
  return [HEADER.join(","), ...rows].join("\r\n");
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
