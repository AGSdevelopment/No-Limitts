// Service Coordinators, HR and Admins: countdown of every staff member's training certificates expiring within 60 days.
import { useState } from "react";
import { FlatList, Pressable, RefreshControl, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Text } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, EmptyState, ErrorState, Ionicons, Loading, formatDate } from "@/src/components/ui";
import { Sheet } from "@/src/components/participant-sheets";
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
  const [nudging, setNudging] = useState<string | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);
  const [nudgingAll, setNudgingAll] = useState(false);
  const toast = useToast();
  const nudgeAll = async () => {
    setNudgingAll(true);
    try {
      const r = await api<any>("/certificates/team/nudge-expired", { method: "POST" });
      toast(r.nudged ? `Reminders sent to ${r.workers} worker${r.workers === 1 ? "" : "s"}` : "Everyone was already reminded today", "success");
      setConfirmAll(false);
      await q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setNudgingAll(false);
    }
  };
  const nudge = async (c: any) => {
    setNudging(c.cert_id);
    try {
      await api(`/certificates/${c.cert_id}/nudge`, { method: "POST" });
      toast(`Reminder sent to ${c.owner_name}`, "success");
      await q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setNudging(null);
    }
  };

  if (!allowed) return <EmptyState icon="lock-closed-outline" title="Not available" subtitle="For Service Coordinators, HR and Admins." />;
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load team certificates." onRetry={q.refetch} />;
  const all = q.data.certificates as any[];
  const rows = all.filter((c) => filter === "all" || c.status === filter);
  const overdue = all.filter((c) => c.status === "expired" && c.owner_id !== user?.user_id && !c.nudged_today);
  const overdueWorkers = new Set(overdue.map((c) => c.owner_id)).size;

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
          {!!overdue.length && (
            <Button label={`Nudge all expired (${overdueWorkers} worker${overdueWorkers === 1 ? "" : "s"})`} icon="notifications-outline"
              onPress={() => setConfirmAll(true)} testID="team-certs-nudge-all" />
          )}
          <Sheet visible={confirmAll} onClose={() => !nudgingAll && setConfirmAll(false)} title="Remind everyone with an expired certificate?"
            sub={`${overdueWorkers} worker${overdueWorkers === 1 ? "" : "s"} will get an app notification and an email for ${overdue.length} expired certificate${overdue.length === 1 ? "" : "s"}. Anyone already reminded today is skipped.`}
            testID="team-certs-nudge-all-sheet">
            <Button label="Send reminders" icon="send-outline" loading={nudgingAll} disabled={nudgingAll} onPress={nudgeAll} testID="team-certs-nudge-all-confirm" />
            <Button label="Cancel" variant="ghost" disabled={nudgingAll} onPress={() => setConfirmAll(false)} />
          </Sheet>
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
              {item.nudged_today ? (
                <Text style={styles.nudged} testID={`team-cert-nudged-${item.cert_id}`}>
                  Reminder sent today{item.nudged_by_name ? ` by ${item.nudged_by_name}` : ""}
                </Text>
              ) : (
                <Pressable onPress={() => nudge(item)} disabled={nudging === item.cert_id} style={styles.nudge}
                  accessibilityRole="button" testID={`team-cert-nudge-${item.cert_id}`}>
                  <Ionicons name="notifications-outline" size={16} color={colors.brandPrimary} />
                  <Text style={styles.nudgeText}>{nudging === item.cert_id ? "Sending…" : "Nudge to renew"}</Text>
                </Pressable>
              )}
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
  nudge: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, alignSelf: "flex-start" },
  nudgeText: { fontSize: 14, fontWeight: "700", color: c.brandPrimary },
  nudged: { fontSize: 13, fontWeight: "600", color: c.successText, marginTop: 6 },
  chip: { minHeight: 44, paddingHorizontal: 14, borderRadius: 22, justifyContent: "center", backgroundColor: c.surface },
  chipOn: { backgroundColor: c.brandPrimary },
  chipText: { fontSize: 13, fontWeight: "600", color: c.onSurface },
  chipTextOn: { color: c.onBrandPrimary },
}));
