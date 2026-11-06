import { Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";
import { Text } from "@/src/components/text";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
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
  const starter = useQuery<any>({ queryKey: ["starter-checklist"], queryFn: () => api("/starter-checklist"), enabled: !!q.data?.is_new_starter });
  const isEmerging = user?.staff_group === "emerging_therapist";
  const newStuff = useQuery<any[]>({ queryKey: ["directory-highlights"], queryFn: () => api("/directory/highlights") });
  const reviews = useQuery<any[]>({ queryKey: ["directory-latest-reviews"], queryFn: () => api("/directory/reviews/latest") });
  const pathway = useQuery<any>({ queryKey: ["pathway"], queryFn: () => api("/pathway"), enabled: isEmerging });
  const d = q.data;
  const mine = (d?.celebrations ?? []).filter((c: any) => c.user_id === user?.user_id);
  const myBirthday = mine.find((c: any) => c.type === "birthday");
  const myAnniversary = mine.find((c: any) => c.type === "anniversary");
  const teamCelebrations = (d?.celebrations ?? []).filter((c: any) => c.user_id !== user?.user_id);
  const myWall = myBirthday ?? myAnniversary;
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;

  const actions: { icon: IconName; label: string; to: any; id: string }[] = [
    { icon: "cloud-upload-outline", label: "Upload", to: "/upload-certificate", id: "upload" },
    user?.role === "admin" || ["support_coordinator", "hr", "support_worker"].includes(user?.user_type ?? "")
      ? { icon: "folder-open-outline", label: "Caseload", to: "/caseload", id: "caseload" }
      : { icon: "sparkles-outline", label: "Ask AI", to: "/assistant", id: "assistant" },
    { icon: "checkbox-outline", label: "Tasks", to: "/tasks", id: "tasks" },
    ...(user?.role === "admin" || user?.user_type === "support_worker" || user?.user_type === "support_coordinator" || (user as any)?.permissions?.length
      ? [{ icon: "people-circle-outline" as IconName, label: "Participants", to: "/pm", id: "pm" }] : []),
    { icon: "clipboard-outline", label: "Forms", to: "/forms", id: "forms" },
    { icon: "calendar-outline", label: "Events", to: "/events", id: "events" },
    { icon: "document-text-outline", label: "Policies", to: "/policies", id: "policies" },
    ...(user?.role === "admin" ? [{ icon: "create-outline" as IconName, label: "Post", to: "/compose?type=update", id: "post" }] : []),
  ];

  return (
    <View style={styles.root} testID="home-screen">
      <TabHeader title="Home">
        <HeaderIcon icon="notifications-outline" badge={d?.unread_notifications} onPress={() => router.push("/notifications")} testID="home-notifications-button" />
      </TabHeader>
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Could not load dashboard data." onRetry={() => q.refetch()} />
      ) : (
        <ScrollView
          contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: bottomChrome + 24 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { q.refetch(); newStuff.refetch(); reviews.refetch(); }} tintColor={colors.brandPrimary} />}
        >
          <Animated.View entering={FadeInDown.duration(400)} style={styles.welcome} testID="home-welcome-card">
            <LinearGradient colors={[colors.highlightSoft, colors.accentSoft, colors.brandSecondary]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={StyleSheet.absoluteFill} />
            <View style={{ flex: 1, gap: 4 }}>
              <Text style={styles.welcomeHi} testID="home-welcome-greeting">
                {myBirthday ? "Happy birthday," : myAnniversary ? `Happy ${myAnniversary.years}-year work anniversary,` : `${greeting()},`}
              </Text>
              <Text style={styles.welcomeName} numberOfLines={1} testID="home-welcome-name">{user?.name?.split(" ")[0] ?? ""}!</Text>
              <Text style={styles.welcomeSub}>
                {myBirthday
                  ? "Wishing you a wonderful day from all of us at No Limitts 🎂"
                  : myAnniversary
                    ? `Thank you for ${myAnniversary.years} year${myAnniversary.years > 1 ? "s" : ""} with No Limitts 🎉`
                    : new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}
              </Text>
              <View style={styles.welcomeDots}>
                {[colors.brandPrimary, colors.accent, colors.sky, colors.highlight].map((c) => <View key={c} style={[styles.welcomeDot, { backgroundColor: c }]} />)}
              </View>
              {!!myWall && (
                <Pressable onPress={() => router.push(`/celebration/${myWall.key}`)} style={styles.wallBtn} testID="home-my-wall" accessibilityLabel="Open your celebration wall">
                  <Text style={styles.wallBtnText}>{myWall.post_count ? `See ${myWall.post_count} message${myWall.post_count > 1 ? "s" : ""}` : "Open your wall"}</Text>
                  <Ionicons name="chevron-forward" size={16} color={colors.onBrandPrimary} />
                </Pressable>
              )}
            </View>
            <Image source={require("@/assets/images/brand-mark.png")} style={styles.welcomeTree} contentFit="contain" />
          </Animated.View>
          {teamCelebrations.map((c: any) => (
            <Pressable key={`${c.type}${c.user_id}`} onPress={() => router.push(`/celebration/${c.key}`)} style={({ pressed }) => [styles.celebrate, pressed && { opacity: 0.85 }]} testID={`home-celebration-${c.type}-${c.user_id}`} accessibilityLabel={`Open ${c.name}'s celebration wall`}>
              <LinearGradient colors={c.type === "birthday" ? [colors.accent, colors.brandPrimary] : [colors.brandPrimary, colors.accent]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={StyleSheet.absoluteFill} />
              <Ionicons name={c.type === "birthday" ? "gift" : "ribbon"} size={26} color="#FFFFFF" />
              <View style={{ flex: 1 }}>
                <Text style={styles.celebrateTitle} numberOfLines={2}>
                  {c.type === "birthday" ? `It's ${c.name}'s birthday today! 🎂` : `${c.name} celebrates ${c.years} year${c.years > 1 ? "s" : ""} with us today! 🎉`}
                </Text>
                <Text style={styles.celebrateSub}>{c.post_count ? `${c.post_count} message${c.post_count > 1 ? "s" : ""} · tap to add yours` : `Tap to congratulate ${c.name.split(" ")[0]}`}</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color="#FFFFFF" />
            </Pressable>
          ))}
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.quickRow} style={{ marginHorizontal: -16 }}>
            {actions.map((a) => (
              <Pressable key={a.id} testID={`quick-action-${a.id}`} onPress={() => router.push(a.to)} style={({ pressed }) => [styles.quick, pressed && { opacity: 0.7 }]}>
                <IconBox name={a.icon} size={44} />
                <Text style={styles.quickLabel}>{a.label}</Text>
              </Pressable>
            ))}
          </ScrollView>

          {!!q.data?.is_new_starter && starter.data && starter.data.done < starter.data.total && (
            <Pressable testID="home-starter-card" onPress={() => router.push("/starter-checklist")} style={({ pressed }) => [styles.starter, pressed && { opacity: 0.85 }]}>
              <Ionicons name="list" size={24} color={colors.onBrandPrimary} />
              <View style={{ flex: 1, gap: 6 }}>
                <Text style={styles.starterTitle}>Your first-week checklist</Text>
                <View style={styles.starterBar}>
                  <View style={[styles.starterFill, { width: `${Math.round((starter.data.done / starter.data.total) * 100)}%` }]} />
                </View>
                <Text style={styles.starterSub}>{starter.data.done} of {starter.data.total} steps done · tap to continue</Text>
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
                    {c.title} — {c.status === "expired" ? `expired ${formatDate(c.expiry_date)}` : `${c.days_left} day${c.days_left === 1 ? "" : "s"} left`}
                  </Text>
                ))}
              </Card>
            </Animated.View>
          )}

          {!!d.team_cert_alerts && (d.team_cert_alerts.expired + d.team_cert_alerts.expiring) > 0 && (
            <Card testID="home-team-cert-card" onPress={() => router.push("/team-certificates")}
              style={[styles.alert, styles.policyCard, d.team_cert_alerts.expired ? styles.alertError : styles.alertWarn]}>
              <Ionicons name="hourglass-outline" size={22} color={d.team_cert_alerts.expired ? colors.errorText : colors.warningText} />
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle}>Team certificates to renew</Text>
                <Text style={styles.rowSub}>
                  {d.team_cert_alerts.expiring ? `${d.team_cert_alerts.expiring} expiring in 60 days` : ""}
                  {d.team_cert_alerts.expiring && d.team_cert_alerts.expired ? " · " : ""}
                  {d.team_cert_alerts.expired ? `${d.team_cert_alerts.expired} expired` : ""}
                </Text>
                {d.team_cert_alerts.soonest.slice(0, 2).map((c: any) => (
                  <Text key={c.cert_id} style={styles.alertLine} numberOfLines={1}>
                    {c.owner_name}: {c.title} — {c.status === "expired" ? "expired" : `${c.days_left} days`}
                  </Text>
                ))}
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.muted} />
            </Card>
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
                    <Text style={styles.rowSub}>{SOCIAL_BRAND[d.latest_social.source] ? d.latest_social.author_name.replace(/^(Aspire & Grow|No Limitts) on /, "") : ""} · {timeAgo(d.latest_social.created_at)}</Text>
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
                          {e.space === "therapist" ? "Support Worker" : "Participants"} · {e.category} · {timeAgo(e.created_at)}{e.file_count ? ` · ${e.file_count} file${e.file_count > 1 ? "s" : ""}` : ""}
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
  root: { flex: 1, backgroundColor: c.background },
  resTitle: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  resSub: { fontSize: 13, color: c.muted },
  reviewStars: { fontSize: 14, color: c.warning, marginTop: 2 },
  reviewText: { fontSize: 14, color: c.onSurface, marginVertical: 4, fontStyle: "italic" },
  welcome: { flexDirection: "row", alignItems: "center", gap: 8, borderRadius: 20, overflow: "hidden", padding: 18, paddingRight: 8, marginTop: 16, minHeight: 140, borderWidth: 1, borderColor: c.border },
  welcomeHi: { fontSize: 15, fontWeight: "600", color: c.onSurfaceSecondary },
  welcomeName: { fontSize: 28, fontWeight: "800", color: c.brandPrimary },
  welcomeSub: { fontSize: 13, color: c.onSurfaceSecondary },
  welcomeDots: { flexDirection: "row", gap: 6, marginTop: 6 },
  welcomeDot: { width: 10, height: 10, borderRadius: 5 },
  welcomeTree: { width: 120, height: 120 },
  wallBtn: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", backgroundColor: c.brandPrimary, borderRadius: 999, paddingHorizontal: 14, minHeight: 36, marginTop: 8 },
  wallBtnText: { fontSize: 13, fontWeight: "700", color: c.onBrandPrimary },
  celebrate: { flexDirection: "row", alignItems: "center", gap: 12, borderRadius: 16, overflow: "hidden", padding: 14, marginTop: 10, minHeight: 64 },
  celebrateTitle: { fontSize: 15, fontWeight: "800", color: "#FFFFFF" },
  celebrateSub: { fontSize: 12.5, fontWeight: "600", color: "#FFFFFF", opacity: 0.92, marginTop: 2 },
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
