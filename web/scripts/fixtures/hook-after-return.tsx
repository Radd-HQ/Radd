// Fixture for hooks-order.test.mjs: the shape of the RADD-1373 account-menu bug.
import { useState } from "react";

declare function useAppearance(): { theme: string };

export function Menu({ signedIn }: { signedIn: boolean }) {
  const [open] = useState(false);
  if (!signedIn) return null;
  const dark = useAppearance().theme === "dark";
  return <div data-open={open} data-dark={dark} />;
}
