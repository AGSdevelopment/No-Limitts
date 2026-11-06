// Timesheets: approved hours per Support Worker per week (Perth time). Finance / Rosters see everyone and export Excel; workers see their own.
import { useState } from "react";
import { FlatList, RefreshControl, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken, openLink } from "@/src/api";
import { Text } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Button, EmptyState, ErrorState, Field, Loading, Pill, dmyToIso, isoToDmy } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const hrs = (n: number) => `${(n ?? 0).toLocaleString("en-AU", { maximumFractionDigits: 2 })} h`;

export default function Timesheets() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const [range, setRange] = useState({ from: "", to: "" });
  const [applied, setApplied] = useState<{ from: string; to: string } | null>(null);
  const q = useQuery<any>({
    queryKey: ["timesheets", applied],
    queryFn: () => api(applied ? `/timesheets?date_from=${applied.from}&date_to=${applied.to}` : "/timesheets"),
  });

  const pick = () => {
    const a = dmyToIso(range.from), b = dmyToIso(range.to);
    if (!a || !b) return null;
    if (a > b) { toast("The start date must be before the end date", "error"); return null; }
    if ((new Date(b).getTime() - new Date(a).getTime()) / 86400000 + 1 > 93) { toast("Choose 1 to 93 days", "error"); return null; }
    return { from: range.from.trim(), to: range.to.trim() };
  };
  const show = () => {
    const r = pick();
    if (r) setApplied(r);
    else if (!dmyToIso(range.from) || !dmyToIso(range.to)) toast("Enter both dates as DD-MM-YYYY", "error");
  };
  const download = () => {
    const d = q.data;
    if (!d) return;
    openLink(`${API_URL}/timesheets/export?date_from=${isoToDmy(d.date_from)}&date_to=${isoToDmy(d.date_to)}&token=${encodeURIComponent(getApiToken() ?? "")}`);
  };

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as any)?.message ?? "Couldn't load timesheets."} onRetry={q.refetch} />;
  const d = q.data;

  return (
    <FlatList
      style={styles.root}
      testID="timesheets-screen"
      data={d.workers}
      keyExtractor={(w: any) => w.worker_id}
      contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}
      ListHeaderComponent={
        <View style={{ gap: 10, marginBottom: 4 }}>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <View style={{ flex: 1 }}><Field label="From" value={range.from} onChangeText={(v) => setRange({ ...range, from: v })} placeholder={isoToDmy(d.date_from)} testID="ts-from" /></View>
            <View style={{ flex: 1 }}><Field label="To" value={range.to} onChangeText={(v) => setRange({ ...range, to: v })} placeholder={isoToDmy(d.date_to)} testID="ts-to" /></View>
          </View>
          <Button label="Show hours" icon="search-outline" variant="secondary" onPress={show} testID="ts-show" />
          <View style={styles.summary} testID="ts-summary">
            <Text style={styles.big}>{hrs(d.total_hours)}</Text>
            <Text style={styles.meta}>approved {d.all_staff ? "for all staff" : "for you"} · {isoToDmy(d.date_from)} to {isoToDmy(d.date_to)}</Text>
            {d.pending > 0 && <Text style={[styles.meta, { color: colors.warningText, fontWeight: "700" }]}>{d.pending} shift{d.pending === 1 ? "" : "s"} still awaiting clock-time approval (not counted yet)</Text>}
          </View>
          {d.all_staff && <Button label="Download Excel timesheets" icon="download-outline" onPress={download} testID="ts-download" />}
        </View>
      }
      ListEmptyComponent={<EmptyState icon="time-outline" title="No hours in this period" subtitle="Completed shifts show here once they're clocked out." />}
      renderItem={({ item: w }) => (
        <View style={styles.card} testID={`ts-worker-${w.worker_id}`}>
          <View style={styles.row}>
            <Text style={[styles.title, { flex: 1 }]}>{w.worker_name}</Text>
            <Text style={styles.title}>{hrs(w.hours)}</Text>
          </View>
          {w.weeks.map((k: any) => (
            <View key={k.week_start} style={styles.row}>
              <Text style={[styles.meta, { flex: 1 }]}>Week of {isoToDmy(k.week_start)} · {k.shifts} shift{k.shifts === 1 ? "" : "s"}</Text>
              {k.pending > 0 && <Pill label={`${k.pending} awaiting`} tone="accent" />}
              <Text style={styles.body}>{hrs(k.hours)}</Text>
            </View>
          ))}
        </View>
      )}
    />
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  card: { backgroundColor: c.surface, borderRadius: 14, padding: 14, gap: 6 },
  summary: { backgroundColor: c.brandTertiary, borderRadius: 14, padding: 14, gap: 4 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  big: { fontSize: 28, fontWeight: "800", color: c.onSurface },
  title: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  body: { fontSize: 14, color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
}));
