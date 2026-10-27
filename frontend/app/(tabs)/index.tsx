import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { HeaderIcon, TabHeader } from "@/src/components/header";
import { Card, EmptyState, ErrorState, IconBox, IconName, Ionicons, Loading, Pill, SectionHeader, formatDate, timeAgo } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { makeStyles, useTheme } from "@/src/theme";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export default function Home() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api("/dashboard"), refetchInterval: 30000 });
  const d = q.data;
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;

  const actions: { icon: IconName; label: string; to: any; id: string }[] = [
    { icon: "cloud-upload-outline", label: "Upload", to: "/upload-certificate", id: "upload" },
    { icon: "sparkles-outline", label: "Ask AI", to: "/assistant", id: "assistant" },
    { icon: "checkbox-outline", label: "Tasks", to: "/tasks", id: "tasks" },
    { icon: "clipboard-outline", label: "Forms", to: "/forms", id: "forms" },
    { icon: "calendar-outline", label: "Events", to: "/events", id: "events" },
    { icon: "document-text-outline", label: "Policies", to: "/policies", id: "policies" },
    ...(user?.role === "admin" ? [{ icon: "create-outline" as IconName, label: "Post", to: "/compose?type=update", id: "post" }] : []),
  ];

  return (
    <View style={styles.root} testID="home-screen">
      <TabHeader title={user?.name?.split(" ")[0] ?? ""} subtitle={greeting()}>
        <HeaderIcon icon="notifications-outline" badge={d?.unread_notifications} onPress={() => router.push("/notifications")} testID="home-notifications-button" />
      </TabHeader>
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Could not load dashboard data." onRetry={() => q.refetch()} />
      ) : (
        <ScrollView
          contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: bottomChrome + 24 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
        >
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.quickRow} style={{ marginHorizontal: -16 }}>
            {actions.map((a) => (
              <Pressable key={a.id} testID={`quick-action-${a.id}`} onPress={() => router.push(a.to)} style={({ pressed }) => [styles.quick, pressed && { opacity: 0.7 }]}>
                <IconBox name={a.icon} size={44} />
                <Text style={styles.quickLabel}>{a.label}</Text>
              </Pressable>
            ))}
          </ScrollView>

          {d.cert_alerts.length > 0 && (
            <Animated.View entering={FadeInDown.delay(50)}>
              <Card
                testID="home-cert-alert-card"
                onPress={() => router.push("/(tabs)/certificates")}
                style={[styles.alert, d.cert_alerts.some((c: any) => c.status === "expired") ? styles.alertError : styles.alertWarn]}
              >
                <View style={styles.alertHead}>
                  <Ionicons name="warning" size={22} color={d.cert_alerts.some((c: any) => c.status === "expired") ? colors.errorText : colors.warningText} />
                  <Text style={styles.alertTitle}>
                    {d.cert_alerts.length} certificate{d.cert_alerts.length > 1 ? "s" : ""} need attention
                  </Text>
                </View>
                {d.cert_alerts.slice(0, 3).map((c: any) => (
                  <Text key={c.cert_id} style={styles.alertLine}>
                    {c.title} — {c.status === "expired" ? `expired ${formatDate(c.expiry_date)}` : `${c.days_left} days left`}
                  </Text>
                ))}
              </Card>
            </Animated.View>
          )}

          {d.pending_policies > 0 && (
            <Card testID="home-pending-policies" onPress={() => router.push("/policies")} style={styles.policyCard}>
              <IconBox name="shield-checkmark-outline" />
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle}>{d.pending_policies} polic{d.pending_policies > 1 ? "ies" : "y"} to review</Text>
                <Text style={styles.rowSub}>Read and acknowledge</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.muted} />
            </Card>
          )}

          <SectionHeader title="My tasks" action="See all" onAction={() => router.push("/tasks")} testID="home-tasks-see-all" />
          {d.open_tasks.length === 0 ? (
            <Card>
              <Text style={styles.rowSub}>You&apos;re all caught up. No open tasks.</Text>
            </Card>
          ) : (
            <Card style={{ paddingVertical: 4 }}>
              {d.open_tasks.slice(0, 3).map((t: any, i: number) => (
                <Pressable key={t.task_id} testID={`home-task-${t.task_id}`} onPress={() => router.push("/tasks")} style={[styles.listRow, i > 0 && styles.rowBorder]}>
                  <Ionicons name="ellipse-outline" size={22} color={colors.brandPrimary} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowTitle} numberOfLines={1}>{t.title}</Text>
                    {!!t.due_date && <Text style={styles.rowSub}>Due {formatDate(t.due_date)}</Text>}
                  </View>
                </Pressable>
              ))}
            </Card>
          )}

          <SectionHeader title="Upcoming events" action="See all" onAction={() => router.push("/events")} testID="home-events-see-all" />
          {d.events.length === 0 ? (
            <Card>
              <Text style={styles.rowSub}>No upcoming events.</Text>
            </Card>
          ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginHorizontal: -16 }} contentContainerStyle={{ paddingHorizontal: 16, gap: 12 }}>
              {d.events.map((e: any) => {
                const dt = new Date(`${e.date}T00:00:00`);
                return (
                  <Card key={e.event_id} testID={`home-event-${e.event_id}`} onPress={() => router.push("/events")} style={styles.eventCard}>
                    <View style={styles.dateBox}>
                      <Text style={styles.dateMonth}>{dt.toLocaleDateString(undefined, { month: "short" }).toUpperCase()}</Text>
                      <Text style={styles.dateDay}>{dt.getDate()}</Text>
                    </View>
                    <Text style={styles.rowTitle} numberOfLines={2}>{e.title}</Text>
                    <Text style={styles.rowSub} numberOfLines={1}>{[e.time, e.location].filter(Boolean).join(" · ") || "All day"}</Text>
                  </Card>
                );
              })}
            </ScrollView>
          )}

          <SectionHeader title="Company updates" action="See all" onAction={() => router.push("/updates")} testID="home-updates-see-all" />
          {d.updates.length === 0 ? (
            <EmptyState icon="megaphone-outline" title="No updates yet" />
          ) : (
            <View style={{ gap: 12 }}>
              {d.updates.map((u: any) => (
                <Card key={u.update_id} testID={`home-update-${u.update_id}`} onPress={() => router.push("/updates")}>
                  <View style={styles.updateMeta}>
                    {u.pinned && <Pill label="Pinned" />}
                    <Text style={styles.rowSub}>{u.author_name} · {timeAgo(u.created_at)}</Text>
                  </View>
                  <Text style={styles.updateTitle}>{u.title}</Text>
                  <Text style={styles.updateBody} numberOfLines={3}>{u.body}</Text>
                </Card>
              ))}
            </View>
          )}
        </ScrollView>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  quickRow: { paddingHorizontal: 16, paddingVertical: 16, gap: 12 },
  quick: { width: 76, alignItems: "center", gap: 6, flexShrink: 0 },
  quickLabel: { fontSize: 12, fontWeight: "600", color: c.onSurfaceSecondary },
  alert: { borderWidth: 0, gap: 6 },
  alertWarn: { backgroundColor: c.warningSoft },
  alertError: { backgroundColor: c.errorSoft },
  alertHead: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 },
  alertTitle: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  alertLine: { fontSize: 14, color: c.onSurfaceSecondary },
  policyCard: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 12 },
  listRow: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 12, minHeight: 52 },
  rowBorder: { borderTopWidth: 0.5, borderTopColor: c.divider },
  rowTitle: { fontSize: 15, fontWeight: "600", color: c.onSurface },
  rowSub: { fontSize: 13, color: c.muted, marginTop: 2 },
  eventCard: { width: 180, gap: 6 },
  dateBox: { width: 48, borderRadius: 10, backgroundColor: c.brandTertiary, alignItems: "center", paddingVertical: 6, marginBottom: 4 },
  dateMonth: { fontSize: 11, fontWeight: "700", color: c.onBrandTertiary },
  dateDay: { fontSize: 20, fontWeight: "700", color: c.onSurface },
  updateMeta: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 },
  updateTitle: { fontSize: 17, fontWeight: "700", color: c.onSurface, marginBottom: 4 },
  updateBody: { fontSize: 14, color: c.onSurfaceSecondary, lineHeight: 20 },
}));
