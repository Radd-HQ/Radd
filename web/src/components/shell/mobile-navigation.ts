import { useSyncExternalStore } from "react";

const media = window.matchMedia("(max-width: 767px)");
let opened = false;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(listener => listener());
media.addEventListener("change", () => { opened = false; notify(); });
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};
export function closeMobileNavigation() { opened = false; notify(); }
export function useMobileNavigation() {
  const mobile = useSyncExternalStore(subscribe, () => media.matches);
  const open = useSyncExternalStore(subscribe, () => opened);
  return { mobile, open, toggle: () => { opened = !opened; notify(); } };
}
