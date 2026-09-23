import { useMemo } from "react";
import { encode } from "uqr";

/**
 * The enrolment QR (GitHub #21 / RADD-1298), encoded HERE from the
 * `otpauth://` URI the setup endpoint already returns — the secret never
 * leaves the page, and the server needs no image dependency.
 *
 * One `<path>` of unit squares over a viewBox the size of the module grid,
 * so it stays sharp at any size. The tile is black-on-white in BOTH themes:
 * scanners expect dark modules on a light field, and an inverted code fails on
 * many authenticator apps — the same deliberate non-themed exception as
 * `text-black` on the roadmap's fixed category fills.
 */
export function TotpQrCode({ uri, size = 176 }: { uri: string; size?: number }) {
  const { path, modules } = useMemo(() => {
    // ecc M: survives a smudged screen; border 4 is the spec's quiet zone.
    const qr = encode(uri, { ecc: "M", border: 4 });
    let d = "";
    qr.data.forEach((row, y) =>
      row.forEach((dark, x) => {
        if (dark) d += `M${x} ${y}h1v1h-1z`;
      }),
    );
    return { path: d, modules: qr.size };
  }, [uri]);

  return (
    <svg
      role="img"
      aria-label="QR code for your authenticator app"
      data-totp-qr
      width={size}
      height={size}
      viewBox={`0 0 ${modules} ${modules}`}
      shapeRendering="crispEdges"
      className="shrink-0 rounded-md bg-white"
    >
      <path d={path} className="fill-black" />
    </svg>
  );
}
