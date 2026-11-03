// Service Coordinators, HR and Admins: countdown of every staff member's training certificates expiring within 60 days.
import { useState } from "react";
import { FlatList, Pressable, RefreshControl, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Text } from "@/src/components/text";
import { Avatar, EmptyState, ErrorState, Loading, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "expiring", label: "Expiring" },
  { key: "expired", label: "Expired" },
] as const;

export default function TeamCertificates() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const allowed = user?.role === "admin" || ["hr", "support_coordinator"].includes(user?.user_type ?? "");
  const q = useQuery<any>({ queryKey: ["team-certificates"], queryFn: () => api("/certificates/team"), enabled: allowed });
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");

  if (!allowed) return <EmptyState icon="lock-closed-outline" title="Not available" subtitle="For Service Coordinators, HR and Admins." />;
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load team certificates." onRetry={q.refetch} />;
  const all = q.data.certificates as any[];
  const rows = all.filter((c) => filter === "all" || c.status === filter);

  return (
    <FlatList
      style={styles.root}
      testID="team-certificates-screen"
      data={rows}
      keyExtractor={(c) => c.cert_id}
      contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}
      ListHeaderComponent={
        <View style={{ gap: 10 }}>
          <Text style={styles.meta}>Training certificates across the team that expire in the next {q.data.warning_days} days, or already have. Staff get reminders too.</Text>
          <View style={styles.chips}>
            {FILTERS.map((f) => {
              const n = f.key === "all" ? all.length : all.filter((c) => c.status === f.key).length;
              return (
                <Pressable key={f.key} onPress={() => setFilter(f.key)} accessibilityRole="button" accessibilityState={{ selected: filter === f.key }}
                  style={[styles.chip, filter === f.key && styles.chipOn]} testID={`team-certs-filter-${f.key}`}>
                  <Text style={[styles.chipText, filter === f.key && styles.chipTextOn]}>{f.label} ({n})</Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      }
      ListEmptyComponent={<EmptyState icon="ribbon-outline" title="All up to date" subtitle="No team certificates are expiring in the next 60 days." />}
      renderItem={({ item }) => {
        const expired = item.status === "expired";
        return (
          <View style={styles.card} testID={`team-cert-${item.cert_id}`}>
            <Avatar name={item.owner_name} size={40} />
            <View style={{ flex: 1 }}>
              <Text style={styles.name}>{item.owner_name}</Text>
              <Text style={styles.body} numberOfLines={2}>{item.title}</Text>
              <Text style={styles.meta}>{expired ? "Expired" : "Expires"} {formatDate(item.expiry_date)}</Text>
            </View>
            <View style={[styles.count, expired ? styles.countError : styles.countWarn]}>
              <Text style={[styles.countNum, { color: expired ? colors.errorText : colors.warningText }]}>
                {expired ? Math.abs(item.days_left) : item.days_left}
              </Text>
              <Text style={[styles.countLabel, { color: expired ? colors.errorText : colors.warningText }]}>
                {expired ? "days ago" : item.days_left === 1 ? "day left" : "days left"}
              </Text>
            </View>
          </View>
        );
      }}
    />
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  card: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 14, padding: 14 },
  name: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  body: { fontSize: 14, color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
  count: { width: 72, borderRadius: 12, paddingVertical: 8, alignItems: "center" },
  countWarn: { backgroundColor: c.warningSoft },
  countError: { backgroundColor: c.errorSoft },
  countNum: { fontSize: 22, fontWeight: "800" },
  countLabel: { fontSize: 11, fontWeight: "600" },
  chips: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  chip: { minHeight: 44, paddingHorizontal: 14, borderRadius: 22, justifyContent: "center", backgroundColor: c.surface },
  chipOn: { backgroundColor: c.brandPrimary },
  chipText: { fontSize: 13, fontWeight: "600", color: c.onSurface },
  chipTextOn: { color: c.onBrandPrimary },
}));
