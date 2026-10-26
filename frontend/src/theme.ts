// Design tokens for this app (light theme). Keys match the "color" block of
// /app/design_guidelines.json. Use makeStyles / useTheme in components.

import { useMemo } from "react";
import { Appearance, StyleSheet, useColorScheme } from "react-native";

export type ColorScheme = "light" | "dark";

const light = {
  surface: "#FFFFFF",
  onSurface: "#11181C",
  surfaceSecondary: "#F2F2F7",
  onSurfaceSecondary: "#3A3A3C",
  surfaceTertiary: "#E5E5EA",
  onSurfaceTertiary: "#1C1C1E",
  surfaceInverse: "#11181C",
  onSurfaceInverse: "#FFFFFF",
  muted: "#8E8E93",

  brand: "#4F7959",
  onBrand: "#FFFFFF",
  brandPrimary: "#4F7959",
  onBrandPrimary: "#FFFFFF",
  brandSecondary: "#E1EFE4",
  onBrandSecondary: "#2E4D36",
  brandTertiary: "#F1F7F3",
  onBrandTertiary: "#4F7959",

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

  border: "#E5E5EA",
  borderStrong: "#C7C7CC",
  divider: "#E5E5EA",
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
