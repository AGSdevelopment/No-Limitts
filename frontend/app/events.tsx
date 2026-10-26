import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { Stack, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, Card, EmptyState, ErrorState, Ionicons, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function Events() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery<any[]>({ queryKey: ["events"], queryFn: () => api("/events") });
  const today = new Date().toISOString().slice(0, 10);
  const events = (q.data ?? []).filter((e) => e.date >= today);

  const rsvp = async (e: any) => {
    try {
      const r = await api(`/events/${e.event_id}/rsvp`, { method: "POST" });
      qc.invalidateQueries({ queryKey: ["events"] });
      toast(r.going ? "You're going!" : "RSVP removed", r.going ? "success" : "info");
    } catch (err: any) {
      toast(err.message, "error");
    }
  };

  return (
    <View style={styles.root} testID="events-screen">
      <Stack.Screen
        options={{
          headerRight:
            user?.role === "admin"
              ? () => (
                  <Pressable testID="events-new-button" onPress={() => router.push("/compose?type=event")} hitSlop={10}>
                    <Ionicons name="add-circle" size={30} color={colors.brandPrimary} style={{ marginRight: 8 }} />
                  </Pressable>
                )
              : undefined,
        }}
      />
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Could not load events." onRetry={() => q.refetch()} />
      ) : (
        <FlatList
          data={events}
          keyExtractor={(e) => e.event_id}
          contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
          ListEmptyComponent={<EmptyState icon="calendar-outline" title="No upcoming events" />}
          renderItem={({ item }) => {
            const dt = new Date(`${item.date}T00:00:00`);
            return (
              <Card testID={`event-${item.event_id}`} style={styles.card}>
                <View style={styles.dateBox}>
                  <Text style={styles.month}>{dt.toLocaleDateString(undefined, { month: "short" }).toUpperCase()}</Text>
                  <Text style={styles.day}>{dt.getDate()}</Text>
                  <Text style={styles.month}>{dt.toLocaleDateString(undefined, { weekday: "short" })}</Text>
                </View>
                <View style={{ flex: 1, gap: 4 }}>
                  <Text style={styles.title}>{item.title}</Text>
                  {(item.time || item.location) && (
                    <Text style={styles.sub}>{[item.time, item.location].filter(Boolean).join(" · ")}</Text>
                  )}
                  {!!item.description && <Text style={styles.desc}>{item.description}</Text>}
                  <Text style={styles.sub}>{item.attendee_count} going</Text>
                  <Button
                    label={item.going ? "Going" : "RSVP"}
                    icon={item.going ? "checkmark-circle" : "add"}
                    variant={item.going ? "secondary" : "primary"}
                    onPress={() => rsvp(item)}
                    style={styles.rsvp}
                    testID={`event-rsvp-${item.event_id}`}
                  />
                </View>
              </Card>
            );
          }}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  card: { flexDirection: "row", gap: 14 },
  dateBox: { width: 56, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", paddingVertical: 8, alignSelf: "flex-start" },
  month: { fontSize: 11, fontWeight: "700", color: c.onBrandTertiary },
  day: { fontSize: 22, fontWeight: "700", color: c.onSurface },
  title: { fontSize: 17, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  desc: { fontSize: 14, color: c.onSurfaceSecondary, lineHeight: 20 },
  rsvp: { alignSelf: "flex-start", minHeight: 40, marginTop: 6 },
}));
