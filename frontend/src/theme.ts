// Design tokens for this app (light theme). Keys match the "color" block of
// /app/design_guidelines.json. Use makeStyles / useTheme in components.

import { useMemo } from "react";
import { Appearance, StyleSheet, useColorScheme } from "react-native";

export type ColorScheme = "light" | "dark";

const light = {
  surface: "#FFFFFF",
  onSurface: "#11181C",
  surfaceSecondary: "#F3F8FD",
  onSurfaceSecondary: "#3A3A3C",
  surfaceTertiary: "#E3F1FE",
  onSurfaceTertiary: "#1C1C1E",
  surfaceInverse: "#163F68",
  onSurfaceInverse: "#FFFFFF",
  muted: "#8E8E93",

  brand: "#205890",
  onBrand: "#FFFFFF",
  brandPrimary: "#205890",
  onBrandPrimary: "#FFFFFF",
  brandSecondary: "#E3F1FE",
  onBrandSecondary: "#205890",
  brandTertiary: "#EEF6FE",
  onBrandTertiary: "#205890",

  accent: "#CD84AC",
  onAccent: "#FFFFFF",
  accentSoft: "#F7E8F0",
  sky: "#86CBDF",
  skySoft: "#E3F1FE",

  success: "#34C759",
  onSuccess: "#FFFFFF",
  successText: "#1E7B3A",
  successSoft: "#E3F7E8",
  warning: "#FF9F0A",
  onWarning: "#FFFFFF",
  warningText: "#9A5B00",
  warningSoft: "#FFF3DF",
  error: "#FF3B30",
  onError: "#FFFFFF",
  errorText: "#B3261E",
  errorSoft: "#FFE7E5",
  info: "#8E8E93",
  onInfo: "#FFFFFF",

  border: "#DCE8F4",
  borderStrong: "#C7C7CC",
  divider: "#E3ECF5",
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
