// Service Coordinators, HR and Admins: month calendar of team certificate expiries. Tap a day to see whose certificates expire.
import { useMemo, useState } from "react";
import { Pressable, RefreshControl, ScrollView, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Text } from "@/src/components/text";
import { Avatar, EmptyState, ErrorState, Ionicons, Loading, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const pad = (n: number) => String(n).padStart(2, "0");

export default function CertCalendar() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const allowed = user?.role === "admin" || ["hr", "support_coordinator"].includes(user?.user_type ?? "");
  const now = new Date();
  const todayIso = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const [ym, setYm] = useState({ y: now.getFullYear(), m: now.getMonth() + 1 });
  const month = `${ym.y}-${pad(ym.m)}`;
  const [day, setDay] = useState<string | null>(null);
  const q = useQuery<any>({ queryKey: ["cert-calendar", month], queryFn: () => api(`/certificates/team/calendar?month=${month}`), enabled: allowed });

  const byDay = useMemo(() => {
    const out: Record<string, any[]> = {};
    for (const c of q.data?.certificates ?? []) (out[c.expiry_date] ??= []).push(c);
    return out;
  }, [q.data]);

  if (!allowed) return <EmptyState icon="lock-closed-outline" title="Not available" subtitle="For Service Coordinators, HR and Admins." />;

  const first = new Date(ym.y, ym.m - 1, 1);
  const lead = (first.getDay() + 6) % 7;
  const days = new Date(ym.y, ym.m, 0).getDate();
  const cells: (number | null)[] = [...Array(lead).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)];
  while (cells.length % 7) cells.push(null);
  const shift = (d: number) => {
    setDay(null);
    setYm(({ y, m }) => {
      const t = new Date(y, m - 1 + d, 1);
      return { y: t.getFullYear(), m: t.getMonth() + 1 };
    });
  };
  const all = (q.data?.certificates ?? []) as any[];
  const list = day ? byDay[day] ?? [] : all;
  const open = all.filter((c) => !c.renewed).length;

  return (
    <ScrollView style={styles.root} contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}
      testID="cert-calendar-screen">
      <View style={styles.monthRow}>
        <Pressable onPress={() => shift(-1)} style={styles.navBtn} accessibilityLabel="Previous month" testID="cert-calendar-prev">
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.monthTitle} testID="cert-calendar-month">
          {first.toLocaleDateString("en-AU", { month: "long", year: "numeric" })}
        </Text>
        <Pressable onPress={() => shift(1)} style={styles.navBtn} accessibilityLabel="Next month" testID="cert-calendar-next">
          <Ionicons name="chevron-forward" size={22} color={colors.onSurface} />
        </Pressable>
      </View>

      <View style={styles.cal}>
        <View style={styles.week}>
          {WEEKDAYS.map((w) => <Text key={w} style={styles.weekday}>{w}</Text>)}
        </View>
        {Array.from({ length: cells.length / 7 }, (_, r) => (
          <View key={r} style={styles.week}>
            {cells.slice(r * 7, r * 7 + 7).map((n, i) => {
              if (!n) return <View key={i} style={styles.cell} />;
              const iso = `${month}-${pad(n)}`;
              const items = byDay[iso] ?? [];
              const pending = items.filter((c) => !c.renewed);
              const sel = day === iso;
              const past = iso < todayIso;
              return (
                <Pressable key={i} onPress={() => setDay(sel ? null : iso)} style={[styles.cell, sel && styles.cellSel]}
                  accessibilityLabel={`${n}, ${items.length} expiring`} testID={`cert-calendar-day-${iso}`}>
                  <Text style={[styles.dayNum, iso === todayIso && styles.today, sel && styles.dayNumSel]}>{n}</Text>
                  {!!items.length && (
                    <View style={[styles.dot, pending.length ? (past ? styles.dotExpired : styles.dotDue) : styles.dotDone]}>
                      <Text style={styles.dotText}>{items.length}</Text>
                    </View>
                  )}
                </Pressable>
              );
            })}
          </View>
        ))}
      </View>

      <View style={styles.legend}>
        <View style={[styles.legendDot, styles.dotDue]} /><Text style={styles.meta}>Due</Text>
        <View style={[styles.legendDot, styles.dotExpired]} /><Text style={styles.meta}>Expired</Text>
        <View style={[styles.legendDot, styles.dotDone]} /><Text style={styles.meta}>Renewed</Text>
      </View>

      <Text style={styles.section}>
        {day ? formatDate(day) : `${all.length} expiring this month${all.length ? ` · ${open} still to renew` : ""}`}
      </Text>
      {q.isLoading ? <Loading /> : q.isError ? <ErrorState message="Couldn't load the calendar." onRetry={q.refetch} /> : !list.length ? (
        <Text style={styles.meta}>{day ? "Nothing expires on this day." : "No team certificates expire this month."}</Text>
      ) : list.map((c) => (
        <View key={c.cert_id} style={styles.card} testID={`cert-calendar-item-${c.cert_id}`}>
          <Avatar name={c.owner_name} size={36} />
          <View style={{ flex: 1 }}>
            <Text style={styles.name}>{c.owner_name}</Text>
            <Text style={styles.body} numberOfLines={2}>{c.title}</Text>
            <Text style={c.renewed ? styles.renewed : styles.meta}>
              {c.renewed ? `✓ Renewed: new one expires ${formatDate(c.renewed.expiry_date)}` : `${c.expiry_date < todayIso ? "Expired" : "Expires"} ${formatDate(c.expiry_date)}`}
            </Text>
          </View>
        </View>
      ))}
    </ScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  monthRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  navBtn: { width: 48, height: 48, alignItems: "center", justifyContent: "center", borderRadius: 24, backgroundColor: c.surface },
  monthTitle: { fontSize: 18, fontWeight: "800", color: c.onSurface },
  cal: { backgroundColor: c.surface, borderRadius: 16, padding: 8, gap: 4 },
  week: { flexDirection: "row" },
  weekday: { flex: 1, textAlign: "center", fontSize: 11, fontWeight: "700", color: c.muted, paddingVertical: 4 },
  cell: { flex: 1, minHeight: 48, alignItems: "center", justifyContent: "flex-start", paddingTop: 4, borderRadius: 10, gap: 2 },
  cellSel: { backgroundColor: c.brandTertiary },
  dayNum: { fontSize: 14, color: c.onSurface },
  dayNumSel: { fontWeight: "800" },
  today: { color: c.brandPrimary, fontWeight: "800" },
  dot: { minWidth: 20, height: 18, borderRadius: 9, alignItems: "center", justifyContent: "center", paddingHorizontal: 4 },
  dotDue: { backgroundColor: c.warningText },
  dotExpired: { backgroundColor: c.errorText },
  dotDone: { backgroundColor: c.successText },
  dotText: { fontSize: 11, fontWeight: "800", color: "#FFFFFF" },
  legend: { flexDirection: "row", alignItems: "center", gap: 6 },
  legendDot: { width: 10, height: 10, borderRadius: 5, marginLeft: 6 },
  section: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  card: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 14, padding: 12 },
  name: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  body: { fontSize: 14, color: c.onSurface },
  meta: { fontSize: 13, color: c.muted },
  renewed: { fontSize: 13, fontWeight: "600", color: c.successText },
}));
