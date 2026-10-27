import { Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

export const usesNativeTabs = Platform.OS === "ios" && parseInt(String(Platform.Version), 10) >= 26;

// Height of the native stack header (status bar + bar), used to offset keyboard avoidance on stack screens.
export function useHeaderHeight() {
  const insets = useSafeAreaInsets();
  return insets.top + (Platform.OS === "ios" ? 44 : Platform.OS === "android" ? 56 : 64);
}
