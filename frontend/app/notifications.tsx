import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { Stack, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { EmptyState, ErrorState, IconBox, IconName, Loading, timeAgo } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const ICONS: Record<string, IconName> = {
  certificate: "ribbon",
  message: "chatbubble",
  update: "megaphone",
  policy: "shield-checkmark",
  event: "calendar",
  task: "checkbox",
};

export default function Notifications() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const qc = useQueryClient();
  const q = useQuery<any[]>({ queryKey: ["notifications"], queryFn: () => api("/notifications") });
  const hasUnread = (q.data ?? []).some((n) => !n.read);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["notifications"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const readAll = async () => {
    await api("/notifications/read-all", { method: "POST" }).catch(() => {});
    refresh();
  };
  const open = async (n: any) => {
    if (!n.read) api(`/notifications/${n.notification_id}/read`, { method: "POST" }).then(refresh).catch(() => {});
    if (n.link) router.push(n.link);
  };

  return (
    <View style={styles.root} testID="notifications-screen">
      <Stack.Screen
        options={{
          headerRight: hasUnread
            ? () => (
                <Pressable testID="notifications-read-all-button" onPress={readAll} hitSlop={10}>
                  <Text style={styles.readAll}>Mark all read</Text>
                </Pressable>
              )
            : undefined,
        }}
      />
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Could not load notifications." onRetry={() => q.refetch()} />
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(n) => n.notification_id}
          contentContainerStyle={{ paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
          ListEmptyComponent={<EmptyState icon="notifications-outline" title="You're all caught up" subtitle="Expiry reminders, new tasks and updates show up here." />}
          renderItem={({ item }) => {
            const urgent = item.type === "certificate";
            return (
              <Pressable
                testID={`notification-${item.notification_id}`}
                onPress={() => open(item)}
                style={({ pressed }) => [styles.row, !item.read && { backgroundColor: colors.brandTertiary }, pressed && { opacity: 0.8 }]}
              >
                <IconBox name={ICONS[item.type] ?? "notifications"} tone={urgent ? (item.title.includes("expired") ? "error" : "warning") : "brand"} />
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={[styles.title, !item.read && { fontWeight: "700" }]}>{item.title}</Text>
                  <Text style={styles.body} numberOfLines={2}>{item.body}</Text>
                  <Text style={styles.time}>{timeAgo(item.created_at)}</Text>
                </View>
                {!item.read && <View style={styles.dot} />}
              </Pressable>
            );
          }}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  readAll: { color: c.brandPrimary, fontWeight: "600", fontSize: 15 },
  row: { flexDirection: "row", gap: 12, paddingHorizontal: 16, paddingVertical: 14, borderBottomWidth: 0.5, borderBottomColor: c.divider, alignItems: "flex-start" },
  title: { fontSize: 15, fontWeight: "600", color: c.onSurface },
  body: { fontSize: 14, color: c.onSurfaceSecondary },
  time: { fontSize: 12, color: c.muted, marginTop: 2 },
  dot: { width: 9, height: 9, borderRadius: 5, backgroundColor: c.brandPrimary, marginTop: 6 },
}));
