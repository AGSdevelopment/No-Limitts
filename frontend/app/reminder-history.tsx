import { useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { EmptyState, ErrorState, Ionicons, Loading, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function ReminderHistory() {
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const [open, setOpen] = useState<string | null>(null);
  const q = useQuery<any[]>({ queryKey: ["reminder-history"], queryFn: () => api("/compliance/reminder-history"), enabled: user?.role === "admin" });

  if (user?.role !== "admin") return <EmptyState icon="lock-closed-outline" title="Admins only" />;
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load reminder history." onRetry={() => q.refetch()} />;

  return (
    <FlatList
      style={styles.root}
      data={q.data}
      keyExtractor={(r) => r.log_id}
      contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} />}
      ListHeaderComponent={<Text style={styles.intro}>Monthly reminders go out automatically on the first Monday of each month at 9am Perth time.</Text>}
      ListEmptyComponent={<EmptyState icon="mail-outline" title="No reminders sent yet" subtitle="They'll appear here once one goes out." />}
      renderItem={({ item }) => {
        const expanded = open === item.log_id;
        return (
          <Pressable onPress={() => setOpen(expanded ? null : item.log_id)} style={styles.card} testID={`reminder-log-${item.log_id}`}>
            <View style={styles.row}>
              <Ionicons name={item.trigger === "monthly" ? "calendar-outline" : "hand-left-outline"} size={22} color={colors.brandPrimary} />
              <View style={{ flex: 1 }}>
                <Text style={styles.title}>
                  {formatDate(item.sent_at)} · {new Date(item.sent_at).toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit", timeZone: "Australia/Perth" })}
                </Text>
                <Text style={styles.sub}>
                  {item.trigger === "monthly" ? "Automatic monthly reminder" : `Sent by ${item.by}`} · {item.recipients.length} staff
                </Text>
              </View>
              <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={20} color={colors.muted} />
            </View>
            {expanded &&
              item.recipients.map((r: any) => (
                <View key={r.user_id} style={styles.recipient}>
                  <Text style={styles.name}>{r.name}</Text>
                  <Text style={styles.sub}>{r.missing?.length ? `Missing: ${r.missing.join(", ")}` : "No certificates on file"}</Text>
                </View>
              ))}
          </Pressable>
        );
      }}
    />
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  intro: { fontSize: 14, color: c.onSurfaceSecondary, marginBottom: 6, lineHeight: 20 },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 14, gap: 10 },
  row: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 44 },
  title: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  recipient: { borderTopWidth: 1, borderTopColor: c.border, paddingTop: 8 },
  name: { fontSize: 14, fontWeight: "600", color: c.onSurface },
}));
