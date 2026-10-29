import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { Image } from "expo-image";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { HeaderIcon, TabHeader } from "@/src/components/header";
import { SOCIAL_BRAND } from "@/src/components/social-post";
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
  const isStarter = !!user?.staff_group?.startsWith("new_starter");
  const starter = useQuery<any>({ queryKey: ["starter-checklist"], queryFn: () => api("/starter-checklist"), enabled: isStarter });
  const isEmerging = user?.staff_group === "emerging_therapist";
  const newStuff = useQuery<any[]>({ queryKey: ["directory-highlights"], queryFn: () => api("/directory/highlights") });
  const reviews = useQuery<any[]>({ queryKey: ["directory-latest-reviews"], queryFn: () => api("/directory/reviews/latest") });
  const dashboards = useQuery<any[]>({ queryKey: ["external-dashboards"], queryFn: () => api("/dashboards") });
  const pathway = useQuery<any>({ queryKey: ["pathway"], queryFn: () => api("/pathway"), enabled: isEmerging });
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
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { q.refetch(); newStuff.refetch(); reviews.refetch(); dashboards.refetch(); }} tintColor={colors.brandPrimary} />}
        >
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.quickRow} style={{ marginHorizontal: -16 }}>
            {actions.map((a) => (
              <Pressable key={a.id} testID={`quick-action-${a.id}`} onPress={() => router.push(a.to)} style={({ pressed }) => [styles.quick, pressed && { opacity: 0.7 }]}>
                <IconBox name={a.icon} size={44} />
                <Text style={styles.quickLabel}>{a.label}</Text>
              </Pressable>
            ))}
          </ScrollView>

          {isStarter && starter.data && starter.data.done < starter.data.total && (
            <Pressable testID="home-starter-card" onPress={() => router.push("/starter-checklist")} style={({ pressed }) => [styles.starter, pressed && { opacity: 0.85 }]}>
              <Ionicons name="list" size={24} color={colors.onBrandPrimary} />
              <View style={{ flex: 1, gap: 6 }}>
                <Text style={styles.starterTitle}>Your New Starter checklist</Text>
                <View style={styles.starterBar}>
                  <View style={[styles.starterFill, { width: `${Math.round((starter.data.done / starter.data.total) * 100)}%` }]} />
                </View>
                <Text style={styles.starterSub}>{starter.data.done} of {starter.data.total} steps done · tap to continue</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={colors.onBrandPrimary} />
            </Pressable>
          )}

          {(dashboards.data ?? []).map((db: any) => (
            <Pressable key={db.dashboard_id} testID={`home-dashboard-${db.dashboard_id}`} onPress={() => router.push(`/dashboard/${db.dashboard_id}`)} style={({ pressed }) => [styles.starter, pressed && { opacity: 0.85 }]} accessibilityLabel={`Open ${db.name}`}>
              <Ionicons name="analytics" size={24} color={colors.onBrandPrimary} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.starterTitle}>Open {db.name.toLowerCase().startsWith("the ") ? db.name : `the ${db.name.toLowerCase()}`}</Text>
                <Text style={styles.starterSub}>Opens right here in the app</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={colors.onBrandPrimary} />
            </Pressable>
          ))}

          {user?.role === "admin" && (
            <Pressable testID="home-plans-overview" onPress={() => router.push("/plans-overview")} style={({ pressed }) => [styles.starter, pressed && { opacity: 0.85 }]} accessibilityLabel="Open the team plans overview">
              <Ionicons name="people" size={24} color={colors.onBrandPrimary} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.starterTitle}>Team plans overview</Text>
                <Text style={styles.starterSub}>Overdue reviews and missing forms for every therapist</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={colors.onBrandPrimary} />
            </Pressable>
          )}

          {isEmerging && pathway.data && (
            <Pressable testID="home-pathway-card" onPress={() => router.push("/pathway")} style={({ pressed }) => [styles.starter, pressed && { opacity: 0.85 }]}>
              <Ionicons name="trending-up" size={24} color={colors.onBrandPrimary} />
              <View style={{ flex: 1, gap: 6 }}>
                <Text style={styles.starterTitle}>My therapist pathway</Text>
                <View style={styles.starterBar}>
                  <View style={[styles.starterFill, { width: `${Math.round((pathway.data.steps_done / pathway.data.steps_total) * 100)}%` }]} />
                </View>
                <Text style={styles.starterSub}>{pathway.data.steps_done} of {pathway.data.steps_total} supervision steps · {pathway.data.goals_done}/{pathway.data.goals.length} CPD goals</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={colors.onBrandPrimary} />
            </Pressable>
          )}

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
                    {d.cert_alerts.length} certificate{d.cert_alerts.length > 1 ? "s need" : " needs"} attention
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

          {!!d.latest_social && (
            <>
              <SectionHeader title="Latest from our socials" action="See all" onAction={() => router.push("/(tabs)/socials")} testID="home-socials-see-all" />
              <Pressable testID="home-social-highlight" onPress={() => d.latest_social.link && openLink(d.latest_social.link)} style={({ pressed }) => [styles.social, pressed && { opacity: 0.85 }]}>
                {d.latest_social.image_url ? (
                  <Image source={{ uri: d.latest_social.image_url }} style={styles.socialImg} contentFit="cover" transition={200} />
                ) : (
                  <View style={[styles.socialImg, styles.socialIconBox, { backgroundColor: SOCIAL_BRAND[d.latest_social.source]?.color }]}>
                    <Ionicons name={SOCIAL_BRAND[d.latest_social.source]?.icon ?? "megaphone"} size={30} color="#FFFFFF" />
                  </View>
                )}
                <View style={{ flex: 1, gap: 4 }}>
                  <View style={styles.socialHead}>
                    <Ionicons name={SOCIAL_BRAND[d.latest_social.source]?.icon ?? "megaphone"} size={14} color={SOCIAL_BRAND[d.latest_social.source]?.color} />
                    <Text style={styles.rowSub}>{SOCIAL_BRAND[d.latest_social.source] ? d.latest_social.author_name.replace("Aspire & Grow on ", "") : ""} · {timeAgo(d.latest_social.created_at)}</Text>
                  </View>
                  <Text style={styles.socialText} numberOfLines={3}>{d.latest_social.body || d.latest_social.title}</Text>
                </View>
              </Pressable>
            </>
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
                  <Card key={e.event_id} testID={`home-event-${e.event_id}`} onPress={() => router.push(`/event/${e.event_id}`)} style={styles.eventCard}>
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

          {d.photo_highlights?.length > 0 && (
            <>
              <SectionHeader title="Event photos" action="See all" onAction={() => router.push("/events")} testID="home-photos-see-all" />
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginHorizontal: -16 }} contentContainerStyle={{ paddingHorizontal: 16, gap: 10 }} testID="home-photo-highlights">
                {d.photo_highlights.map((p: any) => (
                  <Pressable key={p.photo_id} onPress={() => router.push(`/event/${p.event_id}`)} style={styles.photoCard} testID={`home-photo-${p.photo_id}`}>
                    <Image source={{ uri: `${API_URL}/events/${p.event_id}/photos/${p.photo_id}?token=${encodeURIComponent(getApiToken() ?? "")}` }} style={styles.photo} contentFit="cover" transition={200} />
                    <Text style={styles.photoTitle} numberOfLines={1}>{p.event_title}</Text>
                  </Pressable>
                ))}
              </ScrollView>
            </>
          )}

          {(newStuff.data?.length ?? 0) > 0 && (
            <>
              <SectionHeader title="New templates & resources" testID="home-new-resources" />
              <View style={{ gap: 8 }}>
                {newStuff.data!.map((e: any) => (
                  <Card key={e.entry_id} onPress={() => router.push({ pathname: "/directory", params: { space: e.space, category: e.category } })} testID={`home-resource-${e.entry_id}`}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
                      <IconBox name={e.category === "Templates" ? "copy-outline" : "library-outline"} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.resTitle} numberOfLines={1}>{e.name}</Text>
                        <Text style={styles.resSub} numberOfLines={1}>
                          {e.space === "therapist" ? "Therapist" : "Participants"} · {e.category} · {timeAgo(e.created_at)}{e.file_count ? ` · ${e.file_count} file${e.file_count > 1 ? "s" : ""}` : ""}
                        </Text>
                      </View>
                      <Pill label="New" tone="accent" />
                    </View>
                  </Card>
                ))}
              </View>
            </>
          )}

          {(reviews.data?.length ?? 0) > 0 && (
            <>
              <SectionHeader title="Fresh recommendations" testID="home-latest-reviews" />
              <View style={{ gap: 8 }}>
                {reviews.data!.map((r: any, i: number) => (
                  <Card key={`${r.entry_id}${i}`} onPress={() => router.push({ pathname: "/directory", params: { space: r.space, category: r.category } })} testID={`home-review-${r.entry_id}-${i}`}>
                    <Text style={styles.resTitle} numberOfLines={1}>{r.entry_name}</Text>
                    <Text style={styles.reviewStars}>{"★".repeat(r.stars)}{"☆".repeat(5 - r.stars)}</Text>
                    <Text style={styles.reviewText} numberOfLines={3}>“{r.text}”</Text>
                    <Text style={styles.resSub} numberOfLines={1}>{r.name} · {r.category === "Activities" ? "Activity" : "Supplier"} · {timeAgo(r.at)}</Text>
                  </Card>
                ))}
              </View>
            </>
          )}

          <SectionHeader title="Company updates" action="See all" onAction={() => router.push("/updates")} testID="home-updates-see-all" />
          {d.updates.length === 0 ? (
            <EmptyState icon="megaphone-outline" title="No updates yet" />
          ) : (
            <View style={{ gap: 12 }}>
              {d.updates.map((u: any) => (
                <Card key={u.update_id} testID={`home-update-${u.update_id}`} onPress={() => router.push("/updates")}>
                  <View style={styles.updateMeta}>
                    {u.pinned && <Pill label="Pinned" tone="accent" />}
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
  resTitle: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  resSub: { fontSize: 13, color: c.muted },
  reviewStars: { fontSize: 14, color: c.warning, marginTop: 2 },
  reviewText: { fontSize: 14, color: c.onSurface, marginVertical: 4, fontStyle: "italic" },
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
  social: { flexDirection: "row", gap: 12, alignItems: "center", backgroundColor: c.surface, borderRadius: 16, borderWidth: 1, borderColor: c.border, padding: 12 },
  photoCard: { width: 140, gap: 6 },
  photo: { width: 140, height: 140, borderRadius: 14, backgroundColor: c.surfaceSecondary },
  photoTitle: { fontSize: 13, fontWeight: "600", color: c.onSurface },
  socialImg: { width: 76, height: 76, borderRadius: 12, backgroundColor: c.surfaceSecondary },
  socialIconBox: { alignItems: "center", justifyContent: "center" },
  socialHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  socialText: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
  starter: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.brandPrimary, borderRadius: 16, padding: 16, marginBottom: 16 },
  starterTitle: { fontSize: 16, fontWeight: "700", color: c.onBrandPrimary },
  starterBar: { height: 8, borderRadius: 4, backgroundColor: "rgba(255,255,255,0.3)", overflow: "hidden" },
  starterFill: { height: 8, borderRadius: 4, backgroundColor: c.onBrandPrimary },
  starterSub: { fontSize: 13, color: c.onBrandPrimary, opacity: 0.9 },
}));
