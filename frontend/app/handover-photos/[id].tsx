// Coordinators, HR and Admins: every shift handover photo for one participant, newest handover first.
import { useState } from "react";
import { FlatList, Modal, Pressable, RefreshControl, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { Image } from "expo-image";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken } from "@/src/api";
import { Text } from "@/src/components/text";
import { EmptyState, ErrorState, Ionicons, Loading, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Photo = { photo_id: string; caption: string; by_name: string; at: string };
const photoUrl = (id: string) => `${API_URL}/caseload/handover/photos/${id}?token=${encodeURIComponent(getApiToken() ?? "")}`;

export default function HandoverPhotoTimeline() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const q = useQuery<any>({ queryKey: ["handover-timeline", id], queryFn: () => api(`/participants/${id}/handover-photos`) });
  const [viewing, setViewing] = useState<Photo | null>(null);

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as Error).message || "Couldn't load photos."} onRetry={q.refetch} />;

  return (
    <>
      <FlatList
        style={styles.root}
        testID="handover-timeline-screen"
        data={q.data.handovers}
        keyExtractor={(g: any) => g.submission_id}
        contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}
        ListHeaderComponent={q.data.total ? (
          <Text style={styles.meta}>
            {q.data.name} · {q.data.total} photo{q.data.total === 1 ? "" : "s"} across {q.data.handovers.length} handover{q.data.handovers.length === 1 ? "" : "s"}
          </Text>
        ) : null}
        ListEmptyComponent={<EmptyState icon="images-outline" title="No handover photos yet" subtitle="Photos Support Workers add to shift handovers show here." />}
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
  viewer: { flex: 1, backgroundColor: "#000000", paddingHorizontal: 16, gap: 12 },
  viewerText: { fontSize: 15, color: "#FFFFFF", lineHeight: 21 },
  close: { width: 48, height: 48, alignItems: "center", justifyContent: "center" },
}));
