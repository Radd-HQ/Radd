/** Theme + density preferences — per-browser, applied on <html>. A STORE (RADD-1238): readers go
 *  through `useAppearance()`, so a change anywhere re-renders every reader. */

import { useSyncExternalStore } from "react";

const THEME_KEY = "radd.theme";
const DENSITY_KEY = "radd.density";

export const Theme = { dark: "dark", light: "light" } as const;
type ThemeValue = (typeof Theme)[keyof typeof Theme];

export const Density = { normal: "normal", compact: "compact" } as const;
type DensityValue = (typeof Density)[keyof typeof Density];

export interface Appearance {
  theme: ThemeValue;
  density: DensityValue;
}

const listeners = new Set<() => void>();
let snapshot: Appearance = { theme: readTheme(), density: readDensity() };

function readTheme(): ThemeValue {
  try {
    return localStorage.getItem(THEME_KEY) === Theme.light ? Theme.light : Theme.dark;
  } catch {
    return Theme.dark;
  }
}

function readDensity(): DensityValue {
  try {
    return localStorage.getItem(DENSITY_KEY) === Density.compact ? Density.compact : Density.normal;
  } catch {
    return Density.normal;
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // A blocked store still gets the live change; it just does not survive a reload.
  }
}

function publish(next: Appearance): void {
  snapshot = next;
  applyAppearance();
  for (const listener of listeners) listener();
}

export function getTheme(): ThemeValue {
  return snapshot.theme;
}

export function setTheme(theme: ThemeValue): void {
  write(THEME_KEY, theme);
  publish({ ...snapshot, theme });
}

export function setDensity(density: DensityValue): void {
  write(DENSITY_KEY, density);
  publish({ ...snapshot, density });
}

function subscribeAppearance(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getAppearance(): Appearance {
  return snapshot;
}

/** The live preferences — re-renders the caller when either changes. */
export function useAppearance(): Appearance {
  return useSyncExternalStore(subscribeAppearance, getAppearance, getAppearance);
}

/** Stamp the stored preferences onto <html> — called at boot and on change. */
export function applyAppearance(): void {
  const root = document.documentElement;
  root.classList.toggle("light", snapshot.theme === Theme.light);
  root.classList.toggle("compact", snapshot.density === Density.compact);
}
