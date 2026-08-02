import type { ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";

/**
 * Composable table primitives (the `settingsTableClasses` look, as components):
 * quiet row separators instead of gridlines, small uppercase heads, tabular
 * figures for numeric columns via the `numeric` prop. Per-cell padding is
 * fixed by the primitives — pass only layout classes (width, sticky offsets)
 * through `className`.
 *
 *   <Table>
 *     <THead><tr><Th>Name</Th><Th numeric>Hours</Th></tr></THead>
 *     <TBody>{rows.map((r) => <tr key={r.id}><Td>{r.name}</Td><Td numeric>{r.h}</Td></tr>)}</TBody>
 *   </Table>
 */

export function Table({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <table className={`w-full border-separate border-spacing-0 text-left text-[13px] ${className}`}>
      {children}
    </table>
  );
}

export function THead({
  sticky = false,
  className = "",
  children,
}: {
  /** Pin the header row when the table scrolls vertically. */
  sticky?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <thead
      className={
        (sticky ? "[&_th]:sticky [&_th]:top-0 [&_th]:z-10 [&_th]:bg-surface " : "") + className
      }
    >
      {children}
    </thead>
  );
}

export function TBody({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <tbody
      className={
        "[&_tr:not(:last-child)>td]:border-b [&_tr:not(:last-child)>td]:border-subtle/60 " +
        "[&_tr]:transition-colors [&_tr:hover]:bg-overlay/50 " +
        className
      }
    >
      {children}
    </tbody>
  );
}

interface CellProps {
  /** Right-align + tabular figures (durations, counts, dates). */
  numeric?: boolean;
  className?: string;
  children?: ReactNode;
}

export function Th({
  numeric = false,
  className = "",
  children,
  ...props
}: CellProps & ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      {...props}
      className={
        "border-b border-subtle px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-fg-faint " +
        (numeric ? "text-right tnum " : "") +
        className
      }
    >
      {children}
    </th>
  );
}

export function Td({
  numeric = false,
  className = "",
  children,
  ...props
}: CellProps & TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      {...props}
      className={`px-3 py-2.5 text-fg ${numeric ? "text-right tnum " : ""}${className}`}
    >
      {children}
    </td>
  );
}
