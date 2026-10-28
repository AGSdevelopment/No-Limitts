import { RefreshControl, ScrollView, Pressable, Text, View } from "react-native";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { BuddyCard, ProbationCard } from "@/src/components/probation-buddy";
import { Avatar, Button, EmptyState, ErrorState, Ionicons, Loading, Pill, formatDate } from "@/src/components/ui";
import { groupLabel } from "@/src/groups";
import { makeStyles, useTheme } from "@/src/theme";

export default function StaffProfile() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const q = useQuery<any>({ queryKey: ["staff-profile", id], queryFn: () => api(`/staff/${id}/profile`), enabled: user?.role === "admin" && !!id });

  if (user?.role !== "admin") return <EmptyState icon="lock-closed-outline" title="Admins only" />;
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load this profile." onRetry={() => q.refetch()} />;
  const { user: s, certificates, missing_required, cpd, policies, checkins, starter, open_tasks } = q.data;
  const acked = policies.filter((p: any) => p.acknowledged).length;
  const tone = (st: string) => (st === "expired" ? colors.error : st === "expiring" ? colors.warningText : colors.success);

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} />}
      testID="staff-profile-screen"
    >
      <Stack.Screen
        options={{
          headerRight: () => (
            <Pressable
              testID="profile-pdf-button"
              onPress={() => openLink(`${API_URL}/staff/${s.user_id}/profile/pdf?token=${encodeURIComponent(getApiToken() ?? "")}`)}
              hitSlop={10}
              style={styles.pdfBtn}
              accessibilityLabel="Download profile PDF"
            >
              <Ionicons name="document-text-outline" size={20} color={colors.brandPrimary} />
              <Text style={styles.pdfText}>PDF</Text>
            </Pressable>
          ),
        }}
      />
      <View style={styles.hero}>
        <Avatar name={s.name} picture={s.picture} size={56} />
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={styles.name}>{s.name}</Text>
          <Text style={styles.sub} numberOfLines={1}>{s.email}</Text>
          <View style={styles.pills}>
            <Pill label={s.role === "admin" ? "Admin" : "Employee"} tone={s.role === "admin" ? "brand" : "muted"} />
            {!!s.staff_group && <Pill label={groupLabel(s.staff_group)} />}
          </View>
        </View>
      </View>

      <View style={styles.stats}>
        <Stat label="Certificates" value={`${certificates.length}`} />
        <Stat label={`CPD ${cpd.year}`} value={`${cpd.year_hours}h`} />
        <Stat label="Policies" value={`${acked}/${policies.length}`} />
        <Stat label="Open tasks" value={`${open_tasks}`} />
      </View>

      <ProbationCard key={`p${s.start_date}${s.probation_end}`} s={s} onSaved={() => q.refetch()} />
      <BuddyCard s={s} onSaved={() => q.refetch()} />

      {s.staff_group === "emerging_therapist" && <PathwaySummary userId={s.user_id} styles={styles} />}

      {starter && (
        <Button label={`New Starter checklist · ${starter.done}/${starter.total} done`} icon="list-outline" variant="secondary" onPress={() => router.push(`/starter/${s.user_id}`)} testID="profile-starter-button" />
      )}

      <Section title="Certificates" styles={styles}>
        {missing_required.map((n: string) => (
          <Row key={`m${n}`} icon="alert-circle" color={colors.error} title={n} sub="Required for their role, not on file" styles={styles} />
        ))}
        {certificates.length === 0 && missing_required.length === 0 && <Text style={styles.empty}>No certificates uploaded yet.</Text>}
        {certificates.map((c: any) => (
          <Row key={c.cert_id} icon="ribbon-outline" color={tone(c.status)} title={c.title} sub={`${c.status === "expired" ? "Expired" : "Expires"} ${formatDate(c.expiry_date)}`} styles={styles} />
        ))}
      </Section>

      <Section title={`CPD this year · ${cpd.year_hours} hours`} styles={styles}>
        {cpd.logs.length === 0 && <Text style={styles.empty}>No CPD logged yet.</Text>}
        {cpd.logs.map((l: any) => (
          <Row key={l.log_id} icon="school-outline" color={colors.brandPrimary} title={l.title} sub={`${formatDate(l.date)} · ${l.hours}h · ${l.type}`} styles={styles} />
        ))}
        {cpd.total_logs > cpd.logs.length && <Text style={styles.empty}>Showing the latest {cpd.logs.length} of {cpd.total_logs}.</Text>}
      </Section>

      <Section title={`Team events attended · ${q.data.events_attended?.length ?? 0}`} styles={styles}>
        {!q.data.events_attended?.length && <Text style={styles.empty}>No attendance recorded yet.</Text>}
        {(q.data.events_attended ?? []).slice(0, 10).map((e: any) => (
          <Row key={e.event_id} icon="people-outline" color={colors.brandPrimary} title={e.title} sub={formatDate(e.date)} styles={styles} />
        ))}
      </Section>

      <Section title="Check-in history" styles={styles}>
        {checkins.length === 0 && <Text style={styles.empty}>No check-ins yet.</Text>}
        {checkins.map((c: any) => (
          <View key={c.event_id} style={styles.checkin} testID={`profile-checkin-${c.event_id}`}>
            <Text style={styles.rowTitle}>
              {formatDate(c.date)}
              {c.time ? ` at ${c.time}` : ""} · {c.created_by}
            </Text>
            {!!c.outcome && <Text style={[styles.outcome, { color: c.outcome === "On track" ? colors.success : colors.warningText }]}>{c.outcome}</Text>}
            {!!c.notes && <Text style={styles.notes}>{c.notes}</Text>}
            {!c.outcome && !c.notes && <Text style={styles.empty}>No notes recorded.</Text>}
          </View>
        ))}
      </Section>

      <Section title={`Policies · ${acked} of ${policies.length} acknowledged`} styles={styles}>
        {policies.length === 0 && <Text style={styles.empty}>No policies yet.</Text>}
        {[...policies].sort((a: any, b: any) => Number(a.acknowledged) - Number(b.acknowledged)).map((p: any) => (
          <Row key={p.policy_id} icon={p.acknowledged ? "checkmark-circle" : "time-outline"} color={p.acknowledged ? colors.success : colors.warningText} title={p.title} sub={p.acknowledged ? "Acknowledged" : "Not acknowledged yet"} styles={styles} />
        ))}
      </Section>
    </ScrollView>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  const styles = useStyles();
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function Section({ title, children, styles }: { title: string; children: React.ReactNode; styles: any }) {
  return (
    <View style={{ gap: 8 }}>
      <Text style={styles.section}>{title}</Text>
      <View style={styles.card}>{children}</View>
    </View>
  );
}

function Row({ icon, color, title, sub, styles }: { icon: any; color: string; title: string; sub: string; styles: any }) {
  return (
    <View style={styles.row}>
      <Ionicons name={icon} size={20} color={color} />
      <View style={{ flex: 1 }}>
        <Text style={styles.rowTitle}>{title}</Text>
        <Text style={styles.sub}>{sub}</Text>
      </View>
    </View>
  );
}

function PathwaySummary({ userId, styles }: { userId: string; styles: any }) {
  const { colors } = useTheme();
  const q = useQuery<any>({ queryKey: ["staff-pathway", userId], queryFn: () => api(`/pathway/user/${userId}`) });
  if (!q.data) return null;
  const p = q.data;
  return (
    <Section title={`Therapist pathway · ${p.steps_done}/${p.steps_total} steps · ${p.goals_done}/${p.goals.length} goals`} styles={styles}>
      {p.steps.map((s: any) => (
        <Row key={s.key} icon={s.done ? "checkmark-circle" : "ellipse-outline"} color={s.done ? colors.success : colors.muted} title={s.title} sub={s.done ? `Done ${formatDate(s.done_at.slice(0, 10))}` : "Not done yet"} styles={styles} />
      ))}
      {p.goals.map((g: any) => (
        <Row key={g.goal_id} icon={g.done ? "flag" : "flag-outline"} color={g.done ? colors.success : colors.brandPrimary} title={g.title} sub={g.done ? "Goal achieved" : g.due ? `Target ${formatDate(g.due)}` : "CPD goal"} styles={styles} />
      ))}
    </Section>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  pdfBtn: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 44, paddingHorizontal: 8 },
  pdfText: { fontSize: 15, fontWeight: "600", color: c.brandPrimary },
  hero: { flexDirection: "row", gap: 12, alignItems: "center", backgroundColor: c.surface, borderRadius: 16, padding: 16 },
  name: { fontSize: 18, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  pills: { flexDirection: "row", gap: 6, flexWrap: "wrap" },
  stats: { flexDirection: "row", gap: 8 },
  stat: { flex: 1, backgroundColor: c.surface, borderRadius: 14, paddingVertical: 12, alignItems: "center", gap: 2 },
  statValue: { fontSize: 18, fontWeight: "700", color: c.onSurface },
  statLabel: { fontSize: 11, color: c.muted, textAlign: "center" },
  section: { fontSize: 13, fontWeight: "700", color: c.muted, textTransform: "uppercase", marginTop: 8 },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 12, gap: 12 },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  rowTitle: { fontSize: 15, fontWeight: "600", color: c.onSurface },
  empty: { fontSize: 13, color: c.muted },
  checkin: { gap: 4, borderLeftWidth: 3, borderLeftColor: c.brandPrimary, paddingLeft: 10 },
  outcome: { fontSize: 14, fontWeight: "700" },
  notes: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
}));
