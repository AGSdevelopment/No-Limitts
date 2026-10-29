import React, { createContext, useCallback, useContext, useRef, useState } from "react";
import { View } from "react-native";
import { Text } from "@/src/components/text";
import Animated, { FadeInUp, FadeOutUp } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@react-native-vector-icons/ionicons";

import { makeStyles, useTheme } from "@/src/theme";

type ToastType = "success" | "error" | "info";
const ToastCtx = createContext<(msg: string, type?: ToastType) => void>(() => {});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<{ msg: string; type: ToastType; id: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();

  const show = useCallback((msg: string, type: ToastType = "success") => {
    if (timer.current) clearTimeout(timer.current);
    setToast({ msg, type, id: Date.now() });
    timer.current = setTimeout(() => setToast(null), 2600);
  }, []);

  const iconColor = toast?.type === "error" ? colors.error : toast?.type === "success" ? colors.success : colors.onSurfaceInverse;

  return (
    <ToastCtx.Provider value={show}>
      {children}
      {toast && (
        <View pointerEvents="none" style={[styles.wrap, { top: insets.top + 8 }]}>
          <Animated.View key={toast.id} entering={FadeInUp} exiting={FadeOutUp} style={styles.toast} testID="toast-message">
            <Ionicons
              name={toast.type === "error" ? "alert-circle" : toast.type === "success" ? "checkmark-circle" : "information-circle"}
              size={20}
              color={iconColor}
            />
            <Text style={styles.text}>{toast.msg}</Text>
          </Animated.View>
        </View>
      )}
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

const useStyles = makeStyles((c) => ({
  wrap: { position: "absolute", left: 16, right: 16, alignItems: "center" },
  toast: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: c.surfaceInverse,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 12,
    maxWidth: 480,
    shadowColor: "#000",
    shadowOpacity: 0.15,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  text: { color: c.onSurfaceInverse, fontSize: 14, fontWeight: "500", flexShrink: 1 },
}));
