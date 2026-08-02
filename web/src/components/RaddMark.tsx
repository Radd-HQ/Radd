/**
 * Radd brand mark — honey-badger paw with claw swipes, drawn in currentColor
 * (inline copy of web/public/brand/mark-solid.svg; keep the two in sync).
 */
export function RaddMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <g fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
        <path d="M6.6 15.1 L3.9 12.4" />
        <path d="M9.1 10.3 L7.7 5.3" />
        <path d="M15.1 10.2 L16.1 5.1" />
        <path d="M18 11.7 L19.8 8.4" />
      </g>
      <path
        fill="currentColor"
        d="M10.4 12.2 H10.55 V15.775 A0.525 0.525 0 0 0 11.6 15.775 V12.2 H13.0 V15.775 A0.525 0.525 0 0 0 14.05 15.775 V12.2 H14.2 A1.9 1.9 0 0 1 16.1 14.1 V17.9 A1.9 1.9 0 0 1 14.2 19.8 H10.4 A1.9 1.9 0 0 1 8.5 17.9 V14.1 A1.9 1.9 0 0 1 10.4 12.2 Z"
      />
    </svg>
  );
}

/**
 * The app-icon tile: honey-gradient ground + cream mark (matches
 * brand/app-icon.svg). Size and corner radius come from className
 * (e.g. "size-5 rounded", "size-8 rounded-lg").
 */
export function RaddTile({ className }: { className?: string }) {
  return (
    <div
      className={`flex shrink-0 items-center justify-center bg-[linear-gradient(145deg,#F6AE3B,#DD6B0D)] ${className ?? ""}`}
    >
      <RaddMark className="size-[78%] text-[#FFF8ED]" />
    </div>
  );
}
