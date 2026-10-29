// "No Limitts" service badge shown on profiles at 1, 3, 5 and 10 years (counted from the start date).
import { Image } from "expo-image";
import { View } from "react-native";
import { Text } from "@/src/components/text";
import { makeStyles, useTheme } from "@/src/theme";

const MILESTONES = [10, 5, 3, 1];

export function serviceYears(startDate?: string | null): number {
  if (!startDate || !/^\d{4}-\d{2}-\d{2}/.test(startDate)) return 0;
  const [y, m, d] = startDate.slice(0, 10).split("-").map(Number);
  const now = new Date();
  let years = now.getFullYear() - y;
  if (now.getMonth() + 1 < m || (now.getMonth() + 1 === m && now.getDate() < d)) years -= 1;
  return Math.max(0, years);
}

export function MilestoneBadge({ startDate, compact }: { startDate?: string | null; compact?: boolean }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const milestone = MILESTONES.find((m) => serviceYears(startDate) >= m);
  if (!milestone) return null;
  const tone = { 1: colors.highlight, 3: colors.sky, 5: colors.accent, 10: colors.brandPrimary }[milestone]!;
  const onTone = milestone === 1 ? colors.onSurface : "#FFFFFF";
  return (
    <View style={[styles.badge, { backgroundColor: tone }, compact && styles.compact]} testID={`milestone-badge-${milestone}`}
      accessibilityLabel={`${milestone} year No Limitts milestone`}>
      <View style={[styles.mark, compact && { width: 16, height: 16 }]}>
        <Image source={require("@/assets/images/brand-mark.png")} style={{ width: "100%", height: "100%" }} contentFit="contain" />
      </View>
      <Text style={[styles.text, { color: onTone }, compact && { fontSize: 11 }]}>
        {milestone} year{milestone > 1 ? "s" : ""}{compact ? "" : " with No Limitts"}
      </Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  badge: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", borderRadius: 999, paddingVertical: 4, paddingLeft: 4, paddingRight: 10 },
  compact: { paddingVertical: 2, paddingRight: 8, gap: 4 },
  mark: { width: 20, height: 20, borderRadius: 10, backgroundColor: c.surface, padding: 2 },
  text: { fontSize: 12, fontWeight: "800" },
}));
