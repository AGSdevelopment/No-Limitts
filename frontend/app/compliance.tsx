import { useMemo, useState } from "react";
import { FlatList, Pressable, RefreshControl, ScrollView, View } from "react-native";
import { Text, TextInput } from "@/src/components/text";
import { Stack, useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, Chip, ConfirmSheet, EmptyState, ErrorState, Ionicons, Loading, formatDate } from "@/src/components/ui";
import { STAFF_GROUPS, groupLabel } from "@/src/groups";
import { makeStyles, useTheme } from "@/src/theme";

type Filter = "all" | "attention" | "policies" | "certs";
type CpdBand = "any" | "low" | "mid" | "high";
const CPD_BANDS: { key: CpdBand; label: string; test: (h: number) => boolean }[] = [
  { key: "any", label: "Any CPD", test: () => true },
  { key: "low", label: "Under 5h", test: (h) => h < 5 },
  { key: "mid", label: "5–20h", test: (h) => h >= 5 && h < 20 },
  { key: "high", label: "20h+", test: (h) => h >= 20 },
];

export default function Compliance() {
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const [filter, setFilter] = useState<Filter>("attention");
  const [search, setSearch] = useState("");
  const [group, setGroup] = useState<string>("any");
  const [cpdBand, setCpdBand] = useState<CpdBand>("any");
  const [open, setOpen] = useState<string | null>(null);
  const router = useRouter();
  const toast = useToast();
  const [remind, setRemind] = useState<number | null>(null);
  const [sending, setSending] = useState(false);

  const previewRemind = async () => {
    try {
      const r = await api("/compliance/remind-certificates?preview=true", { method: "POST" });
      if (!r.would_remind) toast("Everyone has their certificates on file.", "success");
      else setRemind(r.would_remind);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const sendRemind = async () => {
    setSending(true);
    try {
      const r = await api("/compliance/remind-certificates", { method: "POST" });
      toast(`Reminder sent to ${r.reminded} staff`, "success");
      setRemind(null);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSending(false);
    }
  };
  const q = useQuery<any>({ queryKey: ["compliance"], queryFn: () => api("/compliance"), enabled: user?.role === "admin" });

  const rows = useMemo(() => {
    const all: any[] = q.data?.rows ?? [];
    const s = search.trim().toLowerCase();
    const band = CPD_BANDS.find((b) => b.key === cpdBand)!;
    return all.filter((r) => {
      if (s && !r.name.toLowerCase().includes(s)) return false;
      if (group !== "any" && (r.staff_group ?? "none") !== group) return false;
      if (!band.test(r.cpd_hours)) return false;
      if (filter === "attention") return r.needs_attention;
      if (filter === "policies") return r.policies_pending.length > 0;
      if (filter === "certs") return r.no_certs || r.missing_required.length > 0 || r.certs_expired.length + r.certs_expiring.length > 0;
      return true;
    });
  }, [q.data, filter, search, group, cpdBand]);

  if (user?.role !== "admin") return <EmptyState icon="lock-closed-outline" title="Admins only" />;
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load compliance." onRetry={() => q.refetch()} />;
  const s = q.data.summary;

  const header = (
    <View style={{ gap: 12, marginBottom: 12 }}>
      <View style={styles.statsRow}>
        <Stat label="Policies acknowledged" value={`${s.policy_pct}%`} sub={`${s.fully_acknowledged}/${s.staff} staff fully up to date`} tone={s.policy_pct >= 90 ? "good" : "warn"} testID="compliance-stat-policies" />
        <Stat label="Certificates" value={`${s.no_certs + s.expired_certs}`} sub={`${s.no_certs} with none · ${s.missing_required} missing required · ${s.expired_certs} expired · ${s.expiring_certs} expiring`} tone={s.expired_certs || s.no_certs ? "bad" : s.expiring_certs ? "warn" : "good"} testID="compliance-stat-certs" />
      </View>
      <View style={styles.statsRow}>
        <Stat label={`Avg CPD hours ${q.data.year}`} value={`${s.avg_cpd}`} sub="per staff member" tone="neutral" testID="compliance-stat-cpd" />
        <Stat label="Need attention" value={`${s.needs_attention}`} sub={`of ${s.staff} staff`} tone={s.needs_attention ? "warn" : "good"} testID="compliance-stat-attention" />
      </View>
      <View style={styles.statsRow}>
        <Button label="Required certs" icon="ribbon-outline" variant="secondary" onPress={() => router.push("/cert-requirements")} style={{ flex: 1, paddingHorizontal: 8 }} testID="compliance-requirements-button" />
        <Button label="Remind staff" icon="mail-outline" variant="secondary" onPress={previewRemind} style={{ flex: 1, paddingHorizontal: 8 }} testID="compliance-remind-button" />
      </View>
      <Pressable onPress={() => router.push("/reminder-history")} style={styles.historyLink} testID="compliance-history-link">
        <Ionicons name="time-outline" size={16} color={colors.brandPrimary} />
        <Text style={styles.historyText}>Reminder history</Text>
      </Pressable>
      <View style={styles.searchBox}>
        <Ionicons name="search" size={18} color={colors.muted} />
        <TextInput value={search} onChangeText={setSearch} placeholder="Search staff" placeholderTextColor={colors.muted} style={styles.searchInput} testID="compliance-search" />
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        <Chip label="Needs attention" selected={filter === "attention"} onPress={() => setFilter("attention")} testID="compliance-filter-attention" />
        <Chip label="Policies pending" selected={filter === "policies"} onPress={() => setFilter("policies")} testID="compliance-filter-policies" />
        <Chip label="Certificates" selected={filter === "certs"} onPress={() => setFilter("certs")} testID="compliance-filter-certs" />
        <Chip label="Everyone" selected={filter === "all"} onPress={() => setFilter("all")} testID="compliance-filter-all" />
      </ScrollView>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        <Chip label="All groups" selected={group === "any"} onPress={() => setGroup("any")} testID="compliance-group-any" />
        {STAFF_GROUPS.map((g) => (
          <Chip key={g.key} label={g.label} selected={group === g.key} onPress={() => setGroup(g.key)} testID={`compliance-group-${g.key}`} />
        ))}
        <Chip label="No group" selected={group === "none"} onPress={() => setGroup("none")} testID="compliance-group-none" />
      </ScrollView>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        {CPD_BANDS.map((b) => (
          <Chip key={b.key} label={b.label} selected={cpdBand === b.key} onPress={() => setCpdBand(b.key)} testID={`compliance-cpd-${b.key}`} />
        ))}
      </ScrollView>
      <Text style={styles.sub} testID="compliance-count">{rows.length} staff shown</Text>
    </View>
  );

  return (
    <View style={styles.root} testID="compliance-screen">
      <Stack.Screen
        options={{
          headerRight: () => (
            <Pressable
              testID="compliance-export-button"
              onPress={() => openLink(`${API_URL}/compliance/export?token=${encodeURIComponent(getApiToken() ?? "")}`)}
              hitSlop={10}
              style={styles.exportBtn}
              accessibilityLabel="Download spreadsheet"
            >
              <Ionicons name="download-outline" size={20} color={colors.brandPrimary} />
              <Text style={styles.exportText}>Export</Text>
            </Pressable>
          ),
        }}
      />
      <FlatList
        data={rows}
        keyExtractor={(r) => r.user_id}
        ListHeaderComponent={header}
        contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
        ItemSeparatorComponent={() => <View style={{ height: 8 }} />}
        keyboardShouldPersistTaps="handled"
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
        ListEmptyComponent={<EmptyState icon="checkmark-done-circle-outline" title="All clear" subtitle="No staff match this filter." testID="compliance-empty" />}
        renderItem={({ item }) => {
          const pend = item.policies_pending.length;
          const missing: string[] = item.missing_required ?? [];
          const certIssues = item.certs_expired.length + item.certs_expiring.length + (item.no_certs ? 1 : 0) + missing.length;
          const expanded = open === item.user_id;
          return (
            <Pressable onPress={() => setOpen(expanded ? null : item.user_id)} style={styles.card} testID={`compliance-row-${item.user_id}`}>
              <View style={styles.rowHead}>
                <Avatar name={item.name} picture={item.picture} size={40} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.name}>{item.name}</Text>
                  <Text style={styles.sub}>{groupLabel(item.staff_group) || (item.role === "admin" ? "Admin" : "No group")}</Text>
                </View>
                <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={18} color={colors.muted} />
              </View>
              <View style={styles.badges}>
                <Badge icon="shield-checkmark-outline" text={pend ? `${pend} polic${pend === 1 ? "y" : "ies"} pending` : "Policies done"} tone={pend ? "warn" : "good"} />
                <Badge icon="ribbon-outline" text={item.no_certs ? "No certificates" : item.certs_expired.length ? `${item.certs_expired.length} expired` : item.certs_expiring.length ? `${item.certs_expiring.length} expiring` : `${item.certs_total} certs OK`} tone={item.no_certs || item.certs_expired.length ? "bad" : certIssues ? "warn" : "good"} />
                {missing.length > 0 && <Badge icon="alert-circle-outline" text={`${missing.length} required missing`} tone="bad" />}
                <Badge icon="school-outline" text={`${item.cpd_hours} CPD h`} tone="neutral" />
                {!!item.starter && (
                  <Badge icon="list-outline" text={`Starter ${item.starter.done}/${item.starter.total}`} tone={item.starter.done === item.starter.total ? "good" : "warn"} />
                )}
              </View>
              {expanded && (
                <View style={styles.details} testID={`compliance-details-${item.user_id}`}>
                  {[...item.certs_expired, ...item.certs_expiring].map((c: any, i: number) => (
                    <Text key={`c${i}`} style={[styles.detail, { color: c.status === "expired" ? colors.errorText : colors.warningText }]}>
                      • {c.title}: {c.status === "expired" ? "expired" : "expires"} {formatDate(c.expiry_date)}
                    </Text>
                  ))}
                  {item.no_certs && <Text style={[styles.detail, { color: colors.errorText }]}>• No certificates uploaded yet</Text>}
                  {missing.length > 0 && <Text style={styles.detailHead}>Required certificates missing</Text>}
                  {missing.map((n) => (
                    <Text key={`m${n}`} style={[styles.detail, { color: colors.errorText }]}>• {n}</Text>
                  ))}
                  {pend > 0 && <Text style={styles.detailHead}>Policies not yet acknowledged</Text>}
                  {item.policies_pending.slice(0, 40).map((t: string) => (
                    <Text key={t} style={styles.detail} numberOfLines={1}>• {t}</Text>
                  ))}
                  {pend === 0 && certIssues === 0 && <Text style={styles.detail}>Fully compliant.</Text>}
                  <Button label="View profile" icon="person-outline" variant="secondary" onPress={() => router.push(`/staff/${item.user_id}`)} style={{ marginTop: 8 }} testID={`compliance-profile-${item.user_id}`} />
                  {!!item.starter && (
                    <Button label="View starter checklist" icon="list-outline" variant="secondary" onPress={() => router.push(`/starter/${item.user_id}`)} style={{ marginTop: 8 }} testID={`compliance-starter-${item.user_id}`} />
                  )}
                </View>
              )}
            </Pressable>
          );
        }}
      />
      <ConfirmSheet
        visible={remind !== null}
        title="Send certificate reminders?"
        message={`${remind} staff have no certificates or are missing a required one. Each gets an in-app notification and an email asking them to upload.`}
        confirmLabel={`Remind ${remind} staff`}
        loading={sending}
        onConfirm={sendRemind}
        onClose={() => setRemind(null)}
      />
    </View>
  );
}

type Tone = "good" | "warn" | "bad" | "neutral";

function useTone(tone: Tone) {
  const { colors } = useTheme();
  return {
    good: { bg: colors.successSoft, fg: colors.successText },
    warn: { bg: colors.warningSoft, fg: colors.warningText },
    bad: { bg: colors.errorSoft, fg: colors.errorText },
    neutral: { bg: colors.brandTertiary, fg: colors.brandPrimary },
  }[tone];
}

function Stat({ label, value, sub, tone, testID }: { label: string; value: string; sub: string; tone: Tone; testID: string }) {
  const styles = useStyles();
  const t = useTone(tone);
  return (
    <View style={[styles.stat, { backgroundColor: t.bg }]} testID={testID}>
      <Text style={[styles.statValue, { color: t.fg }]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={styles.statSub}>{sub}</Text>
    </View>
  );
}

function Badge({ icon, text, tone }: { icon: any; text: string; tone: Tone }) {
  const styles = useStyles();
  const t = useTone(tone);
  return (
    <View style={[styles.badge, { backgroundColor: t.bg }]}>
      <Ionicons name={icon} size={13} color={t.fg} />
      <Text style={[styles.badgeText, { color: t.fg }]}>{text}</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  exportBtn: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 44, paddingHorizontal: 8 },
  exportText: { fontSize: 15, fontWeight: "600", color: c.brandPrimary },
  statsRow: { flexDirection: "row", gap: 10 },
  historyLink: { flexDirection: "row", alignItems: "center", alignSelf: "flex-start", gap: 6, minHeight: 44, paddingHorizontal: 4 },
  historyText: { fontSize: 14, fontWeight: "600", color: c.brandPrimary },
  stat: { flex: 1, borderRadius: 16, padding: 14, gap: 2 },
  statValue: { fontSize: 28, fontWeight: "800" },
  statLabel: { fontSize: 13, fontWeight: "700", color: c.onSurface },
  statSub: { fontSize: 12, color: c.onSurfaceSecondary },
  searchBox: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 44, borderRadius: 12, backgroundColor: c.surface, paddingHorizontal: 12 },
  searchInput: { flex: 1, fontSize: 16, color: c.onSurface, minHeight: 44 },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 14, gap: 10 },
  rowHead: { flexDirection: "row", alignItems: "center", gap: 12 },
  name: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  badges: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  badge: { flexDirection: "row", alignItems: "center", gap: 4, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  badgeText: { fontSize: 12, fontWeight: "600" },
  details: { gap: 4, borderTopWidth: 0.5, borderTopColor: c.divider, paddingTop: 10 },
  detailHead: { fontSize: 13, fontWeight: "700", color: c.onSurface, marginTop: 4 },
  detail: { fontSize: 13, color: c.onSurfaceSecondary },
}));
