import { useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { EmptyState, ErrorState, Ionicons, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Item = { name: string; end: string; days_to_end: number; review?: string; days_overdue?: number };
type Page = {
  dashboard_id: string; name: string; owners: string[]; participants: number;
  overdue: Item[]; due_30: Item[]; ending_30: Item[]; booked: Item[]; forms: { name: string; issues: string[] }[];
};

// Admins: every therapist's plan reviews and form gaps on one screen
export default function PlansOverview() {
  const { user } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const isAdmin = user?.role === "admin";
  const q = useQuery<any>({ queryKey: ["plans-overview"], queryFn: () => api("/agts-dashboard/team-overview"), enabled: isAdmin });

  if (!isAdmin) return <EmptyState icon="lock-closed-outline" title="Admins only" />;
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load the plans overview." onRetry={() => q.refetch()} />;
  const pages: Page[] = q.data?.pages ?? [];
  const t = q.data?.totals ?? {};

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
      testID="plans-overview-screen"
    >
      <View style={styles.tiles}>
        <Tile label="Reviews overdue" value={t.overdue ?? 0} tone="bad" />
        <Tile label="Forms to action" value={t.forms ?? 0} tone="warn" />
        <Tile label="Reviews due ≤30 days" value={t.due_30 ?? 0} tone="warn" />
        <Tile label="Plans ending ≤30 days" value={t.ending_30 ?? 0} tone="bad" />
      </View>
      <Text style={styles.sub}>As of {q.data?.today}. Booked reviews don&apos;t count as overdue. Tap a therapist to see the names.</Text>
      <Pressable
        onPress={() => openLink(`${API_URL}/agts-dashboard/team-overview/pdf?token=${encodeURIComponent(getApiToken() ?? "")}`)}
        style={({ pressed }) => [styles.pdf, pressed && { opacity: 0.85 }]}
        accessibilityLabel="Download the overview as a PDF"
        testID="plans-overview-pdf"
      >
        <Ionicons name="document-text-outline" size={18} color={colors.onBrandPrimary} />
        <Text style={styles.pdfText}>PDF for team meeting</Text>
      </Pressable>
      {pages.length === 0 ? (
        <EmptyState icon="document-text-outline" title="No plan data yet" subtitle="Upload the plans export on Nikki's plans page first." />
      ) : (
        pages.map((p) => <TherapistCard key={p.dashboard_id} p={p} onOpen={() => router.push(`/dashboard/${p.dashboard_id}`)} />)
      )}
    </ScrollView>
  );
}

function Tile({ label, value, tone }: { label: string; value: number; tone: "bad" | "warn" }) {
  const styles = useStyles();
  return (
    <View style={styles.tile}>
      <Text style={[styles.tileNum, value > 0 && (tone === "bad" ? styles.bad : styles.warn)]}>{value}</Text>
      <Text style={styles.tileLabel}>{label}</Text>
    </View>
  );
}

function TherapistCard({ p, onOpen }: { p: Page; onOpen: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [open, setOpen] = useState(p.overdue.length + p.forms.length > 0);
  const who = p.owners.join(", ") || p.name;
  return (
    <View style={styles.card} testID={`plans-overview-${p.dashboard_id}`}>
      <Pressable onPress={() => setOpen(!open)} style={styles.cardHead} accessibilityRole="button" accessibilityLabel={`${who}, ${open ? "hide" : "show"} details`}>
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={styles.name}>{who}</Text>
          <Text style={styles.sub}>{p.participants} active participant{p.participants === 1 ? "" : "s"} · {p.booked.length} review{p.booked.length === 1 ? "" : "s"} booked</Text>
        </View>
        <Ionicons name={open ? "chevron-up" : "chevron-down"} size={20} color={colors.muted} />
      </Pressable>
      <View style={styles.pills}>
        <Pill n={p.overdue.length} label="overdue" tone="bad" />
        <Pill n={p.forms.length} label="forms" tone="warn" />
        <Pill n={p.due_30.length} label="due soon" tone="warn" />
        <Pill n={p.ending_30.length} label="ending" tone="bad" />
      </View>
      {open && (
        <View style={{ gap: 10 }}>
          <Section title="Reviews overdue" rows={p.overdue.map((r) => [r.name, `due ${r.review} · ${r.days_overdue}d ago`])} tone="bad" />
          <Section title="Forms to action" rows={p.forms.map((f) => [f.name, f.issues.join(", ")])} tone="warn" />
          <Section title="Reviews due in 30 days" rows={p.due_30.map((r) => [r.name, `due ${r.review}`])} tone="warn" />
          <Section title="Plans ending in 30 days" rows={p.ending_30.map((r) => [r.name, `ends ${r.end}`])} tone="bad" />
          <Section title="Reviews booked" rows={p.booked.map((r) => [r.name, r.review ? `booked for ${r.review}` : "booked"])} tone="good" />
          {!p.overdue.length && !p.forms.length && !p.due_30.length && !p.ending_30.length && <Text style={styles.sub}>All up to date 🎉</Text>}
          <Pressable onPress={onOpen} style={({ pressed }) => [styles.open, pressed && { opacity: 0.8 }]} testID={`plans-overview-open-${p.dashboard_id}`}>
            <Text style={styles.openText}>Open plans page</Text>
            <Ionicons name="chevron-forward" size={16} color={colors.onBrandSecondary} />
          </Pressable>
        </View>
      )}
    </View>
  );
}

function Pill({ n, label, tone }: { n: number; label: string; tone: "bad" | "warn" }) {
  const styles = useStyles();
  return (
    <View style={[styles.pill, n > 0 && (tone === "bad" ? styles.pillBad : styles.pillWarn)]}>
      <Text style={[styles.pillText, n > 0 && (tone === "bad" ? styles.bad : styles.warn)]}>{n} {label}</Text>
    </View>
  );
}

function Section({ title, rows, tone }: { title: string; rows: string[][]; tone: "bad" | "warn" | "good" }) {
  const styles = useStyles();
  if (!rows.length) return null;
  return (
    <View style={{ gap: 4 }}>
      <Text style={[styles.secTitle, tone === "bad" ? styles.bad : tone === "warn" ? styles.warn : styles.good]}>{title} ({rows.length})</Text>
      {rows.map(([a, b], i) => (
        <View key={`${a}-${i}`} style={styles.row}>
          <Text style={styles.rowName} numberOfLines={1}>{a}</Text>
          <Text style={styles.rowInfo}>{b}</Text>
        </View>
      ))}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  tiles: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  tile: { flexBasis: "48%", flexGrow: 1, backgroundColor: c.surface, borderRadius: 16, padding: 12, gap: 2 },
  tileNum: { fontSize: 26, fontWeight: "800", color: c.onSurface },
  tileLabel: { fontSize: 13, color: c.muted },
  sub: { fontSize: 13, color: c.muted },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 14, gap: 10 },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 44 },
  name: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  pills: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, backgroundColor: c.surfaceSecondary },
  pillBad: { backgroundColor: c.errorSoft },
  pillWarn: { backgroundColor: c.warningSoft },
  pillText: { fontSize: 12.5, fontWeight: "600", color: c.muted },
  bad: { color: c.errorText },
  warn: { color: c.warningText },
  good: { color: c.successText },
  secTitle: { fontSize: 14, fontWeight: "700" },
  row: { gap: 1, paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: c.divider },
  rowName: { fontSize: 14.5, fontWeight: "600", color: c.onSurface },
  rowInfo: { fontSize: 13, color: c.onSurfaceSecondary },
  open: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, minHeight: 44, borderRadius: 12, backgroundColor: c.brandSecondary },
  openText: { color: c.onBrandSecondary, fontWeight: "600", fontSize: 14 },
  pdf: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 48, borderRadius: 14, backgroundColor: c.brandPrimary },
  pdfText: { color: c.onBrandPrimary, fontWeight: "700", fontSize: 15 },
}));
