import { useState } from "react";
import { FlatList, RefreshControl, View } from "react-native";
import { Text } from "@/src/components/text";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";

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
  const eventsAllowed = user?.role === "admin" || user?.staff_group === "support_office";
  const streaksAllowed = user?.role === "admin" || ["support_worker", "support_coordinator", "hr"].includes(user?.user_type ?? "");
  const params = useLocalSearchParams<{ tab?: string }>();
  const [tab, setTab] = useState<"events" | "streaks" | "renewals">(
    params.tab === "renewals" ? "renewals" : params.tab === "streaks" || !eventsAllowed ? "streaks" : "events");
  const q = useQuery<any>({ queryKey: ["leaderboard", period], queryFn: () => api(`/events/leaderboard?period=${period}`), enabled: eventsAllowed && tab === "events" });
  const sq = useQuery<any>({ queryKey: ["streak-board"], queryFn: () => api("/caseload/streaks"), enabled: streaksAllowed && tab === "streaks" });
  const rq = useQuery<any>({ queryKey: ["renewal-board"], queryFn: () => api("/certificates/renewal-board"), enabled: tab !== "events" });
  const badges: Record<string, { emoji: string; label: string }> = {};
  for (const r of rq.data?.rows ?? []) if (r.badge) badges[r.user_id] = r.badge;

  if (!eventsAllowed && !streaksAllowed) return <EmptyState icon="lock-closed-outline" title="Not available for your role" />;

  const tabs = (
    <View style={[styles.chips, { flexWrap: "wrap" }]}>
      {eventsAllowed && <Chip label="Team events" selected={tab === "events"} onPress={() => setTab("events")} testID="leaderboard-tab-events" />}
      {streaksAllowed && <Chip label="Case note streaks" selected={tab === "streaks"} onPress={() => setTab("streaks")} testID="leaderboard-tab-streaks" />}
      <Chip label="On-time renewals" selected={tab === "renewals"} onPress={() => setTab("renewals")} testID="leaderboard-tab-renewals" />
    </View>
  );

  if (tab === "renewals") {
    return (
      <FlatList
        style={styles.root}
        data={rq.data?.rows ?? []}
        keyExtractor={(r) => r.user_id}
        contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={rq.isRefetching} onRefresh={() => rq.refetch()} tintColor={colors.brandPrimary} />}
        testID="renewal-board-screen"
        ListHeaderComponent={
          <View style={{ gap: 10, marginBottom: 4 }}>
            {tabs}
            <Text style={styles.sub}>Staff who upload their renewed certificate before the old one expires. Keep the streak going to earn a badge:</Text>
            <View style={[styles.chips, { flexWrap: "wrap" }]}>
              {(rq.data?.badges ?? []).map((b: any) => (
                <View key={b.label} style={styles.badgeKey}>
                  <Text style={styles.badgeKeyText}>{b.emoji} {b.label} · {b.streak}+</Text>
                </View>
              ))}
            </View>
          </View>
        }
        ListEmptyComponent={
          rq.isLoading ? <Loading /> : rq.isError ? <ErrorState message="Couldn't load renewals." onRetry={() => rq.refetch()} /> : <EmptyState icon="ribbon-outline" title="No renewals yet" subtitle="Renew a certificate before it expires to get on the board." />
        }
        renderItem={({ item, index }) => (
          <View style={[styles.card, index < 3 && item.streak > 0 && styles.top, item.me && styles.me]} testID={`renewal-row-${item.user_id}`}>
            <Text style={styles.rank}>{item.streak > 0 ? MEDALS[index] ?? `${index + 1}` : "–"}</Text>
            <Avatar name={item.name} picture={item.picture} size={40} />
            <View style={{ flex: 1 }}>
              <Text style={styles.name}>{item.name}{item.me ? " (you)" : ""}</Text>
              <Text style={styles.sub}>{item.on_time} of {item.renewals} renewed on time</Text>
              {!!item.badge && <Text style={styles.badge} testID={`renewal-badge-${item.user_id}`}>{item.badge.emoji} {item.badge.label}</Text>}
            </View>
            <View style={styles.score}>
              <Text style={styles.scoreNum}>{item.streak}</Text>
              <Text style={styles.scoreLabel}>in a row</Text>
            </View>
          </View>
        )}
      />
    );
  }

  if (tab === "streaks") {
    return (
      <FlatList
        style={styles.root}
        data={sq.data?.rows ?? []}
        keyExtractor={(r) => r.user_id}
        contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={sq.isRefetching} onRefresh={() => sq.refetch()} tintColor={colors.brandPrimary} />}
        testID="streak-board-screen"
        ListHeaderComponent={
          <View style={{ gap: 10, marginBottom: 4 }}>
            {tabs}
            <Text style={styles.sub}>Support Workers with the longest run of days completing their case notes. Days off don&apos;t break a streak.</Text>
          </View>
        }
        ListEmptyComponent={
          sq.isLoading ? <Loading /> : sq.isError ? <ErrorState message="Couldn't load streaks." onRetry={() => sq.refetch()} /> : <EmptyState icon="flame-outline" title="No streaks yet" subtitle="Complete case notes on consecutive days to get on the board." />
        }
        renderItem={({ item, index }) => (
          <View style={[styles.card, index < 3 && item.current > 0 && styles.top, item.me && styles.me]} testID={`streak-row-${item.user_id}`}>
            <Text style={styles.rank}>{item.current > 0 ? MEDALS[index] ?? `${index + 1}` : "–"}</Text>
            <Avatar name={item.name} picture={item.picture} size={40} />
            <View style={{ flex: 1 }}>
              <Text style={styles.name}>{item.name}{item.me ? " (you)" : ""}{badges[item.user_id] ? ` ${badges[item.user_id].emoji}` : ""}</Text>
              <Text style={styles.sub}>Best {item.best} day{item.best === 1 ? "" : "s"}{item.today_done ? " · today done" : ""}</Text>
            </View>
            <View style={styles.score}>
              <Text style={styles.scoreNum}>🔥 {item.current}</Text>
              <Text style={styles.scoreLabel}>day{item.current === 1 ? "" : "s"}</Text>
            </View>
          </View>
        )}
      />
    );
  }

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
          {tabs}
          <View style={styles.chips}>
            <Chip label="This year" selected={period === "year"} onPress={() => setPeriod("year")} testID="leaderboard-period-year" />
            <Chip label="All time" selected={period === "all"} onPress={() => setPeriod("all")} testID="leaderboard-period-all" />
          </View>
          {q.data && <Text style={styles.sub}>{q.data.events_counted} past team event{q.data.events_counted === 1 ? "" : "s"} counted. Uses the organiser&apos;s attendance check-in, or &quot;going&quot; RSVPs where none was taken.</Text>}
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
  root: { flex: 1, backgroundColor: c.background },
  chips: { flexDirection: "row", gap: 8 },
  card: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 16, padding: 12 },
  top: { borderWidth: 1, borderColor: c.brandPrimary },
  me: { backgroundColor: c.brandTertiary },
  rank: { width: 32, textAlign: "center", fontSize: 20, fontWeight: "800", color: c.onSurface },
  name: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  score: { alignItems: "center", minWidth: 48 },
  scoreNum: { fontSize: 22, fontWeight: "800", color: c.brandPrimary },
  scoreLabel: { fontSize: 11, color: c.muted },
  badge: { fontSize: 12, fontWeight: "700", color: c.brandPrimary, marginTop: 2 },
  badgeKey: { backgroundColor: c.surface, borderRadius: 12, paddingHorizontal: 10, paddingVertical: 6 },
  badgeKeyText: { fontSize: 12, fontWeight: "600", color: c.onSurface },
}));
