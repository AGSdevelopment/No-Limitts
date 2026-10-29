// Design tokens for this app (light theme). Keys match the "color" block of
// /app/design_guidelines.json. Use makeStyles / useTheme in components.

import { useMemo } from "react";
import { Appearance, StyleSheet, useColorScheme } from "react-native";

export type ColorScheme = "light" | "dark";

const light = {
  surface: "#FCFEFF",
  onSurface: "#11181C",
  surfaceSecondary: "#F7F3FA",
  onSurfaceSecondary: "#3A3A3C",
  surfaceTertiary: "#EFE8F5",
  onSurfaceTertiary: "#1C1C1E",
  surfaceInverse: "#3E2358",
  onSurfaceInverse: "#FFFFFF",
  muted: "#8E8E93",

  brand: "#673E8D",
  onBrand: "#FFFFFF",
  brandPrimary: "#673E8D",
  onBrandPrimary: "#FFFFFF",
  brandSecondary: "#EFE8F5",
  onBrandSecondary: "#673E8D",
  brandTertiary: "#F6F1FA",
  onBrandTertiary: "#673E8D",

  accent: "#EB3F7F",
  onAccent: "#FFFFFF",
  accentSoft: "#FDE7EF",
  sky: "#F7A51D",
  skySoft: "#FEF3DE",
  highlight: "#EBE837",
  highlightSoft: "#FBFAD7",

  success: "#34C759",
  onSuccess: "#FFFFFF",
  successText: "#1E7B3A",
  successSoft: "#E3F7E8",
  warning: "#F7A51D",
  onWarning: "#FFFFFF",
  warningText: "#9A5B00",
  warningSoft: "#FFF3DF",
  error: "#FF3B30",
  onError: "#FFFFFF",
  errorText: "#B3261E",
  errorSoft: "#FFE7E5",
  info: "#8E8E93",
  onInfo: "#FFFFFF",

  border: "#E6DDEF",
  borderStrong: "#C7C7CC",
  divider: "#EEE7F4",
  scrim: "rgba(17,24,28,0.4)",
};

export type ThemeColors = typeof light;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, xxxl: 48 };
export const radius = { sm: 6, md: 12, lg: 20, pill: 999 };
export const font = { sm: 12, base: 14, lg: 16, xl: 20, xxl: 24, display: 30 };

export const defaultScheme = "light" satisfies ColorScheme;

export const themes: { light: ThemeColors; dark?: ThemeColors } = { light };

export function setColorScheme(scheme: ColorScheme | null) {
  Appearance.setColorScheme?.(scheme ?? "unspecified");
}

setColorScheme?.(themes.dark ? null : defaultScheme);

export const colors = light;

export function useTheme(): { scheme: ColorScheme; colors: ThemeColors } {
  const system = useColorScheme();
  const scheme: ColorScheme = (system === "light" || system === "dark") && themes[system] ? system : defaultScheme;
  return { scheme, colors: themes[scheme] ?? themes.light };
}

export function makeStyles<T extends StyleSheet.NamedStyles<T> | StyleSheet.NamedStyles<any>>(
  factory: (colors: ThemeColors) => T & StyleSheet.NamedStyles<any>,
): () => T {
  return function useStyles(): T {
    const { colors } = useTheme();
    return useMemo(() => StyleSheet.create(factory(colors)), [colors]);
  };
}
