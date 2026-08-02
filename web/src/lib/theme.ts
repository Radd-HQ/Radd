/** Theme + density preferences (spec 39) — per-browser, applied on <html>. */

const THEME_KEY = "radd.theme";
const DENSITY_KEY = "radd.density";

export const Theme = { dark: "dark", light: "light" } as const;
export type ThemeValue = (typeof Theme)[keyof typeof Theme];

export const Density = { normal: "normal", compact: "compact" } as const;
export type DensityValue = (typeof Density)[keyof typeof Density];

export function getTheme(): ThemeValue {
  return localStorage.getItem(THEME_KEY) === Theme.light ? Theme.light : Theme.dark;
}

export function getDensity(): DensityValue {
  return localStorage.getItem(DENSITY_KEY) === Density.compact
    ? Density.compact
    : Density.normal;
}

export function setTheme(theme: ThemeValue): void {
  localStorage.setItem(THEME_KEY, theme);
  applyAppearance();
}

export function setDensity(density: DensityValue): void {
  localStorage.setItem(DENSITY_KEY, density);
  applyAppearance();
}

/** Stamp the stored preferences onto <html> — called at boot and on change. */
export function applyAppearance(): void {
  const root = document.documentElement;
  root.classList.toggle("light", getTheme() === Theme.light);
  root.classList.toggle("compact", getDensity() === Density.compact);
}
