interface TableSkeletonProps {
  rows?: number;
}

/** Pulsing placeholder rows shown while a settings list/table loads. */
export function TableSkeleton({ rows = 4 }: TableSkeletonProps) {
  return (
    <div aria-hidden className="animate-pulse rounded-lg border border-subtle">
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          className="flex items-center gap-3 border-b border-subtle/80 px-4 py-3 last:border-b-0"
        >
          <div className="h-3 w-24 rounded bg-elevated" />
          <div className="h-3 w-40 rounded bg-elevated/70" />
          <div className="ml-auto h-3 w-16 rounded bg-elevated/50" />
        </div>
      ))}
    </div>
  );
}
