import { useState } from "react";
import { FlatList, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { Stack, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Chip, EmptyState, ErrorState, Ionicons, Loading, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function Tasks() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const q = useQuery<any[]>({ queryKey: ["tasks", scope], queryFn: () => api(`/tasks?scope=${scope}`) });
  const today = new Date().toISOString().slice(0, 10);

  const toggle = async (t: any) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
    const status = t.status === "done" ? "open" : "done";
    qc.setQueryData(["tasks", scope], (old: any[] = []) => old.map((x) => (x.task_id === t.task_id ? { ...x, status } : x)));
    try {
      await api(`/tasks/${t.task_id}`, { method: "PATCH", body: { status } });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (status === "done") toast("Task completed");
    } catch (e: any) {
      toast(e.message, "error");
    }
    qc.invalidateQueries({ queryKey: ["tasks"] });
  };

  return (
    <View style={styles.root} testID="tasks-screen">
      <Stack.Screen
        options={{
          headerRight: isAdmin
            ? () => (
                <Pressable testID="tasks-new-button" onPress={() => router.push("/compose?type=task")} hitSlop={10}>
                  <Ionicons name="add-circle" size={30} color={colors.brandPrimary} style={{ marginRight: 8 }} />
                </Pressable>
              )
            : undefined,
        }}
      />
      {isAdmin && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow} contentContainerStyle={styles.chipContent}>
          <Chip label="My tasks" selected={scope === "mine"} onPress={() => setScope("mine")} testID="tasks-scope-mine" />
          <Chip label="All assigned" selected={scope === "all"} onPress={() => setScope("all")} testID="tasks-scope-all" />
        </ScrollView>
      )}
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Could not load tasks." onRetry={() => q.refetch()} />
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(t) => t.task_id}
          contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
          ListEmptyComponent={<EmptyState icon="checkbox-outline" title="No tasks" subtitle="Tasks assigned to you will appear here." />}
          renderItem={({ item }) => {
            const done = item.status === "done";
            const overdue = !done && item.due_date && item.due_date < today;
            const canToggle = isAdmin || item.assignee_id === user?.user_id;
            return (
              <Pressable
                testID={`task-${item.task_id}`}
                disabled={!canToggle}
                onPress={() => toggle(item)}
                style={({ pressed }) => [styles.row, pressed && { opacity: 0.8 }]}
              >
                <Ionicons
                  name={done ? "checkmark-circle" : "ellipse-outline"}
                  size={26}
                  color={done ? colors.success : colors.brandPrimary}
                  testID={`task-toggle-${item.task_id}`}
                />
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={[styles.title, done && styles.doneText]}>{item.title}</Text>
                  {!!item.description && <Text style={styles.desc} numberOfLines={2}>{item.description}</Text>}
                  <Text style={[styles.sub, overdue && { color: colors.errorText, fontWeight: "600" }]}>
                    {[scope === "all" ? item.assignee_name : `From ${item.created_by}`, item.due_date ? `${overdue ? "Overdue · " : "Due "}${formatDate(item.due_date)}` : ""]
                      .filter(Boolean)
                      .join(" · ")}
                  </Text>
                </View>
              </Pressable>
            );
          }}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  chipRow: { flexGrow: 0, height: 56, backgroundColor: c.surface },
  chipContent: { paddingHorizontal: 16, gap: 8, alignItems: "center" },
  row: { flexDirection: "row", alignItems: "flex-start", gap: 12, backgroundColor: c.surface, borderRadius: 14, padding: 14, minHeight: 56 },
  title: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  doneText: { textDecorationLine: "line-through", color: c.muted },
  desc: { fontSize: 14, color: c.onSurfaceSecondary },
  sub: { fontSize: 13, color: c.muted, marginTop: 2 },
}));
