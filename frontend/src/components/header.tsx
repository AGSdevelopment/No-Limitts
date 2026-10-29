import React from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/src/components/text";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Ionicons, IconName } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export function TabHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: React.ReactNode }) {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  return (
    <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
      <View style={styles.row}>
        <View style={{ flex: 1 }}>
          {subtitle && <Text style={styles.subtitle}>{subtitle}</Text>}
          <Text style={styles.title} numberOfLines={1}>
            {title}
          </Text>
        </View>
        <View style={styles.actions}>{children}</View>
      </View>
    </View>
  );
}

export function HeaderIcon({ icon, onPress, badge, testID }: { icon: IconName; onPress: () => void; badge?: number; testID: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <Pressable testID={testID} onPress={onPress} style={({ pressed }) => [styles.iconBtn, pressed && { opacity: 0.6 }]} hitSlop={6}>
      <Ionicons name={icon} size={22} color={colors.onSurface} />
      {!!badge && badge > 0 && (
        <View style={styles.badge} testID={`${testID}-badge`}>
          <Text style={styles.badgeText}>{badge > 99 ? "99+" : badge}</Text>
        </View>
      )}
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  header: { backgroundColor: c.background, paddingHorizontal: 16, paddingBottom: 12, borderBottomWidth: 0.5, borderBottomColor: c.divider },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  subtitle: { fontSize: 14, color: c.muted, fontWeight: "500", marginBottom: 2 },
  title: { fontSize: 30, fontWeight: "700", color: c.onSurface, letterSpacing: -0.8 },
  actions: { flexDirection: "row", gap: 8 },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center" },
  badge: {
    position: "absolute",
    top: 4,
    right: 4,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    paddingHorizontal: 4,
    backgroundColor: c.error,
    alignItems: "center",
    justifyContent: "center",
  },
  badgeText: { color: c.onError, fontSize: 10, fontWeight: "700" },
}));
