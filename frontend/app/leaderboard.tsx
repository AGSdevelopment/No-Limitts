import { useState } from "react";
import { FlatList, RefreshControl, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Avatar, Chip, EmptyState, ErrorState, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const MEDALS = ["🥇", "🥈", "🥉"];

export default function Leaderboard() {
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const [period, setPeriod] = useState<"year" | "all">("year");
  const allowed = user?.role === "admin" || user?.staff_group === "support_office";
  const q = useQuery<any>({ queryKey: ["leaderboard", period], queryFn: () => api(`/events/leaderboard?period=${period}`), enabled: allowed });

  if (!allowed) return <EmptyState icon="lock-closed-outline" title="Admins and Support Office only" />;

  return (
    <FlatList
      style={styles.root}
      data={q.data?.rows ?? []}
      keyExtractor={(r) => r.user_id}
      contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
      testID="leaderboard-screen"
      ListHeaderComponent={
        <View style={{ gap: 10, marginBottom: 4 }}>
          <View style={styles.chips}>
            <Chip label="This year" selected={period === "year"} onPress={() => setPeriod("year")} testID="leaderboard-period-year" />
            <Chip label="All time" selected={period === "all"} onPress={() => setPeriod("all")} testID="leaderboard-period-all" />
          </View>
          {q.data && <Text style={styles.sub}>{q.data.events_counted} past team event{q.data.events_counted === 1 ? "" : "s"} counted. Uses the organiser's attendance check-in, or "going" RSVPs where none was taken.</Text>}
        </View>
      }
      ListEmptyComponent={
        q.isLoading ? <Loading /> : q.isError ? <ErrorState message="Couldn't load the leaderboard." onRetry={() => q.refetch()} /> : <EmptyState icon="trophy-outline" title="No event attendance yet" subtitle="Once team events have happened, the most engaged staff show here." />
      }
      renderItem={({ item, index }) => (
        <View style={[styles.card, index < 3 && styles.top]} testID={`leaderboard-row-${item.user_id}`}>
          <Text style={styles.rank}>{MEDALS[index] ?? `${index + 1}`}</Text>
          <Avatar name={item.name} size={40} />
          <View style={{ flex: 1 }}>
            <Text style={styles.name}>{item.name}</Text>
            <Text style={styles.sub}>
              {item.attended} checked in{item.rsvp_only ? ` · ${item.rsvp_only} by RSVP` : ""}
            </Text>
          </View>
          <View style={styles.score}>
            <Text style={styles.scoreNum}>{item.events}</Text>
            <Text style={styles.scoreLabel}>event{item.events === 1 ? "" : "s"}</Text>
          </View>
        </View>
      )}
    />
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  chips: { flexDirection: "row", gap: 8 },
  card: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 16, padding: 12 },
  top: { borderWidth: 1, borderColor: c.brandPrimary },
  rank: { width: 32, textAlign: "center", fontSize: 20, fontWeight: "800", color: c.onSurface },
  name: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  score: { alignItems: "center", minWidth: 48 },
  scoreNum: { fontSize: 22, fontWeight: "800", color: c.brandPrimary },
  scoreLabel: { fontSize: 11, color: c.muted },
}));
