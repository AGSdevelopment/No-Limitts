// Missed case notes: participants with a Support Worker assigned and the recent days with no Support Worker case note.
import { useState } from "react";
import { FlatList, Pressable, RefreshControl, View } from "react-native";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Text } from "@/src/components/text";
import { Avatar, EmptyState, ErrorState, Ionicons, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const RANGES = [7, 14, 30];

function short(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short" });
}

export default function MissedNotes() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [days, setDays] = useState(7);
  const [refreshing, setRefreshing] = useState(false);
  const q = useQuery<any>({ queryKey: ["missed-notes", days], queryFn: () => api(`/caseload/missed?days=${days}`), retry: false });

  return (
    <FlatList
      style={styles.root}
      testID="missed-notes-screen"
      data={q.data?.participants ?? []}
      keyExtractor={(p) => p.participant_id}
      contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={refreshing} tintColor={colors.brandPrimary}
        onRefresh={async () => { setRefreshing(true); await q.refetch(); setRefreshing(false); }} />}
      ListHeaderComponent={
        <View style={{ gap: 10 }}>
          <Text style={styles.meta}>Days with no Support Worker case note, for participants who have a Support Worker assigned. Today isn&apos;t counted yet.</Text>
          <View style={styles.chips}>
            {RANGES.map((r) => (
              <Pressable key={r} onPress={() => setDays(r)} style={[styles.chip, days === r && styles.chipOn]} accessibilityRole="button"
                accessibilityState={{ selected: days === r }} testID={`missed-range-${r}`}>
                <Text style={[styles.chipText, days === r && styles.chipTextOn]}>Last {r} days</Text>
              </Pressable>
            ))}
          </View>
        </View>
      }
      ListEmptyComponent={
        q.isLoading ? <Loading /> : q.isError ? (
          <ErrorState message={(q.error as any)?.message ?? "Couldn't load the report"} onRetry={q.refetch} />
        ) : (
          <EmptyState icon="checkmark-done-outline" title="No missed case notes" subtitle={`Every assigned participant had a case note each day in the last ${days} days.`} />
        )
      }
      renderItem={({ item }) => (
        <Pressable onPress={() => router.push(`/participant/${item.participant_id}`)} style={styles.card} testID={`missed-${item.name}`}>
          <View style={styles.head}>
            <Avatar name={item.name} size={40} />
            <View style={{ flex: 1 }}>
              <Text style={styles.name}>{item.name}</Text>
              <Text style={styles.meta}>{item.missing.length} day{item.missing.length === 1 ? "" : "s"} missed · {item.assigned} Support Worker{item.assigned === 1 ? "" : "s"}</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.muted} />
          </View>
          <View style={styles.days}>
            {item.missing.map((d: string) => (
              <View key={d} style={styles.day}><Text style={styles.dayText}>{short(d)}</Text></View>
            ))}
          </View>
        </Pressable>
      )}
    />
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
  chips: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  chip: { minHeight: 44, paddingHorizontal: 14, borderRadius: 22, justifyContent: "center", backgroundColor: c.surface },
  chipOn: { backgroundColor: c.brandPrimary },
  chipText: { fontSize: 13, fontWeight: "600", color: c.onSurface },
  chipTextOn: { color: c.onBrandPrimary },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 14, gap: 10 },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  name: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  days: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  day: { backgroundColor: c.warningSoft, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 6 },
  dayText: { fontSize: 12, fontWeight: "600", color: c.onSurface },
}));
