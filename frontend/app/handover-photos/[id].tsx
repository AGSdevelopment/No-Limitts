// Coordinators, HR and Admins: every shift handover photo for one participant, newest handover first.
import { useState } from "react";
import { FlatList, Modal, Pressable, RefreshControl, ScrollView, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { Image } from "expo-image";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken } from "@/src/api";
import { Text } from "@/src/components/text";
import { Chip, EmptyState, ErrorState, Field, Ionicons, Loading, dmyToIso, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Photo = { photo_id: string; caption: string; by_name: string; at: string };
const photoUrl = (id: string) => `${API_URL}/caseload/handover/photos/${id}?token=${encodeURIComponent(getApiToken() ?? "")}`;

const RANGES = [
  { key: "all", label: "Any time" },
  { key: "7", label: "Last 7 days" },
  { key: "30", label: "Last 30 days" },
  { key: "90", label: "Last 90 days" },
  { key: "custom", label: "Custom dates" },
] as const;
type Range = (typeof RANGES)[number]["key"];

function rangeDates(range: Range, from: string, to: string): { from?: string; to?: string } {
  if (range === "all") return {};
  if (range === "custom") return { from: dmyToIso(from) || undefined, to: dmyToIso(to) || undefined };
  const d = new Date(Date.now() - (Number(range) - 1) * 86400000);
  return { from: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}` };
}

export default function HandoverPhotoTimeline() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [worker, setWorker] = useState("");
  const [range, setRange] = useState<Range>("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const q = useQuery<any>({ queryKey: ["handover-timeline", id, worker, range, from, to], queryFn: () => {
    const qs = new URLSearchParams();
    if (worker) qs.set("worker", worker);
    const r = rangeDates(range, from, to);
    if (r.from) qs.set("date_from", r.from);
    if (r.to) qs.set("date_to", r.to);
    return api(`/participants/${id}/handover-photos?${qs.toString()}`);
  }, placeholderData: (prev) => prev, enabled: range !== "custom" || ((!from || !!dmyToIso(from)) && (!to || !!dmyToIso(to))
    && !(dmyToIso(from) && dmyToIso(to) && (dmyToIso(from) as string) > (dmyToIso(to) as string))) });
  const [viewing, setViewing] = useState<Photo | null>(null);

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as Error).message || "Couldn't load photos."} onRetry={q.refetch} />;
  if (!q.data) return <Loading />;
  const filtered = !!worker || range !== "all";
  const badFrom = range === "custom" && !!from && !dmyToIso(from);
  const badTo = range === "custom" && !!to && !dmyToIso(to);
  const isoFrom = range === "custom" ? dmyToIso(from) : null;
  const isoTo = range === "custom" ? dmyToIso(to) : null;
  const dateHint = badFrom || badTo ? "Enter dates as DD-MM-YYYY to filter."
    : isoFrom && isoTo && isoFrom > isoTo ? "The start date must be before the end date." : "";

  const filters = (
    <View style={{ gap: 10 }} testID="timeline-filters">
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        <Chip label="All workers" selected={!worker} onPress={() => setWorker("")} testID="timeline-worker-all" />
        {q.data.workers.map((w: any) => (
          <Chip key={w.user_id} label={w.name} selected={worker === w.user_id} onPress={() => setWorker(w.user_id)} testID={`timeline-worker-${w.user_id}`} />
        ))}
      </ScrollView>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
        {RANGES.map((r) => (
          <Chip key={r.key} label={r.label} selected={range === r.key} onPress={() => setRange(r.key)} testID={`timeline-range-${r.key}`} />
        ))}
      </ScrollView>
      {range === "custom" && (
        <View style={{ flexDirection: "row", gap: 8 }}>
          <View style={{ flex: 1 }}><Field label="From" value={from} onChangeText={setFrom} placeholder="DD-MM-YYYY" testID="timeline-from" /></View>
          <View style={{ flex: 1 }}><Field label="To" value={to} onChangeText={setTo} placeholder="DD-MM-YYYY" testID="timeline-to" /></View>
        </View>
      )}
      {!!dateHint && <Text style={styles.hint} testID="timeline-date-hint">{dateHint}</Text>}
      {q.data.all_total > 0 && (
        <Text style={styles.meta}>
          {q.data.total} photo{q.data.total === 1 ? "" : "s"} across {q.data.handovers.length} handover{q.data.handovers.length === 1 ? "" : "s"}
          {filtered ? ` (of ${q.data.all_total})` : ""}
        </Text>
      )}
    </View>
  );

  return (
    <>
      <FlatList
        style={styles.root}
        testID="handover-timeline-screen"
        data={q.data.handovers}
        keyExtractor={(g: any) => g.submission_id}
        contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}
        ListHeaderComponent={q.data.all_total ? filters : null}
        ListEmptyComponent={filtered
          ? <EmptyState icon="filter-outline" title="No photos match" subtitle="Try another worker or date range." />
          : <EmptyState icon="images-outline" title="No handover photos yet" subtitle="Photos Support Workers add to shift handovers show here." />}
        renderItem={({ item }: { item: any }) => (
          <View style={styles.card} testID={`timeline-handover-${item.submission_id}`}>
            <View style={styles.headRow}>
              <Ionicons name="swap-horizontal-outline" size={16} color={colors.brandPrimary} />
              <Text style={styles.date}>{formatDate(item.date)}</Text>
              <Text style={styles.meta} numberOfLines={1}>· {item.photos.length} photo{item.photos.length === 1 ? "" : "s"}</Text>
            </View>
            <View style={styles.grid}>
              {item.photos.map((p: Photo) => (
                <Pressable key={p.photo_id} onPress={() => setViewing(p)} style={styles.cell} accessibilityLabel={`Photo from ${p.by_name}`}
                  testID={`timeline-photo-${p.photo_id}`}>
                  <Image source={{ uri: photoUrl(p.photo_id) }} style={styles.thumb} contentFit="cover" />
                  <Text style={styles.cap} numberOfLines={2}>{p.caption || p.by_name}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        )}
      />
      <Modal visible={!!viewing} animationType="fade" onRequestClose={() => setViewing(null)}>
        <View style={[styles.viewer, { paddingTop: insets.top + 8, paddingBottom: insets.bottom + 16 }]} testID="timeline-viewer">
          <View style={styles.headRow}>
            <Text style={[styles.viewerText, { flex: 1 }]}>{viewing ? `${viewing.by_name} · ${formatDate(viewing.at)}` : ""}</Text>
            <Pressable onPress={() => setViewing(null)} style={styles.close} accessibilityLabel="Close photo" testID="timeline-viewer-close">
              <Ionicons name="close" size={26} color="#FFFFFF" />
            </Pressable>
          </View>
          {viewing && <Image source={{ uri: photoUrl(viewing.photo_id) }} style={{ flex: 1 }} contentFit="contain" />}
          {!!viewing?.caption && <Text style={styles.viewerText}>{viewing.caption}</Text>}
        </View>
      </Modal>
    </>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  card: { backgroundColor: c.surface, borderRadius: 14, padding: 12, gap: 10 },
  headRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  date: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  cell: { width: "31%" },
  thumb: { width: "100%", aspectRatio: 1, borderRadius: 10, backgroundColor: c.surfaceSecondary },
  cap: { fontSize: 11, color: c.muted, marginTop: 2 },
  hint: { fontSize: 13, fontWeight: "600", color: c.errorText },
  viewer: { flex: 1, backgroundColor: "#000000", paddingHorizontal: 16, gap: 12 },
  viewerText: { fontSize: 15, color: "#FFFFFF", lineHeight: 21 },
  close: { width: 48, height: 48, alignItems: "center", justifyContent: "center" },
}));
