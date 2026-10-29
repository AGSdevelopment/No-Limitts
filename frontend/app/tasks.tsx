import { useState } from "react";
import { FlatList, Pressable, RefreshControl, ScrollView, View } from "react-native";
import { Text } from "@/src/components/text";
import { Stack, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Chip, ConfirmSheet, EmptyState, ErrorState, Ionicons, Loading, formatDate } from "@/src/components/ui";
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
  const [del, setDel] = useState<any>(null);
  const q = useQuery<any[]>({ queryKey: ["tasks", scope], queryFn: () => api(`/tasks?scope=${scope}`) });
  const today = new Date().toISOString().slice(0, 10);

  const remove = async () => {
    try {
      await api(del.progress ? `/tasks/group/${del.group_id}` : `/tasks/${del.task_id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast("Task deleted", "info");
    } catch (e: any) {
      toast(e.message, "error");
    }
    setDel(null);
  };

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
          headerRight: () => (
            <Pressable testID="tasks-new-button" onPress={() => router.push("/compose?type=task")} hitSlop={10} accessibilityLabel="New task">
              <Ionicons name="add-circle" size={30} color={colors.brandPrimary} style={{ marginRight: 8 }} />
            </Pressable>
          ),
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
          ListEmptyComponent={<EmptyState icon="checkbox-outline" title="No tasks" subtitle="Tap + to add a private task, or wait for tasks assigned to you." />}
          renderItem={({ item }) => {
            const done = item.status === "done";
            const overdue = !done && item.due_date && item.due_date < today;
            const isGroup = Array.isArray(item.progress);
            const canToggle = !isGroup && (isAdmin || item.assignee_id === user?.user_id);
            const canDelete = item.created_by_id === user?.user_id || (isAdmin && !item.private);
            const who = item.private ? "Only you" : isGroup ? (item.for_everyone ? "Everyone" : `${item.progress.length} people`) : scope === "all" ? item.assignee_name : `From ${item.created_by}`;
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
                  {isGroup && <GroupProgress item={item} />}
                  {item.collaborators?.length > 0 && !isGroup && (
                    <View style={styles.subRow} testID={`task-collaborators-${item.task_id}`}>
                      <Ionicons name="people" size={13} color={colors.brandPrimary} />
                      <Text style={styles.collab} numberOfLines={2}>
                        {scope === "all" ? "Shared with" : "Working on this with"} {item.collaborators.map((c: any) => c.name).join(", ")}
                      </Text>
                    </View>
                  )}
                  {!!item.for_everyone && scope !== "all" && (
                    <View style={styles.subRow}>
                      <Ionicons name="people" size={13} color={colors.muted} />
                      <Text style={styles.sub}>Assigned to everyone</Text>
                    </View>
                  )}
                  {!!item.attachment && (
                    <Pressable
                      testID={`task-attachment-${item.task_id}`}
                      onPress={() => openLink(`${API_URL}/tasks/files/${item.attachment.file_id}?token=${encodeURIComponent(getApiToken() ?? "")}`)}
                      hitSlop={6}
                      style={styles.attach}
                    >
                      <Ionicons name="attach" size={16} color={colors.brandPrimary} />
                      <Text style={styles.attachText} numberOfLines={1}>{item.attachment.file_name}</Text>
                    </Pressable>
                  )}
                  <View style={styles.subRow}>
                    {item.private && <Ionicons name="lock-closed" size={12} color={colors.muted} />}
                    <Text style={[styles.sub, overdue && { color: colors.errorText, fontWeight: "600" }]}>
                      {[who, item.due_date ? `${overdue ? "Overdue · " : "Due "}${formatDate(item.due_date)}` : ""].filter(Boolean).join(" · ")}
                    </Text>
                  </View>
                </View>
                {canDelete && (
                  <Pressable testID={`task-delete-${item.task_id}`} onPress={() => setDel(item)} hitSlop={6} style={styles.delBtn} accessibilityLabel="Delete task">
                    <Ionicons name="trash-outline" size={19} color={colors.muted} />
                  </Pressable>
                )}
              </Pressable>
            );
          }}
        />
      )}
      <ConfirmSheet visible={!!del} title="Delete task?" message={del?.private ? "This removes your private task." : del?.progress ? `This removes the task for all ${del.progress.length} assignees.` : "This removes the task for its assignee."} confirmLabel="Delete" onConfirm={remove} onClose={() => setDel(null)} />
    </View>
  );
}

function GroupProgress({ item }: { item: any }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  const total = item.progress.length;
  const pct = total ? item.done_count / total : 0;
  return (
    <View style={styles.progress} testID={`task-progress-${item.group_id}`}>
      <Pressable onPress={() => setOpen((o) => !o)} hitSlop={6} style={styles.progressHead} testID={`task-progress-toggle-${item.group_id}`}>
        <View style={styles.bar}>
          <View style={[styles.barFill, { width: `${Math.round(pct * 100)}%` }]} />
        </View>
        <Text style={styles.progressText}>{item.done_count} of {total} done</Text>
        <Ionicons name={open ? "chevron-up" : "chevron-down"} size={16} color={colors.muted} />
      </Pressable>
      {open &&
        item.progress.map((p: any) => (
          <View key={p.task_id} style={styles.personRow} testID={`task-progress-person-${p.task_id}`}>
            <Ionicons name={p.status === "done" ? "checkmark-circle" : "ellipse-outline"} size={18} color={p.status === "done" ? colors.success : colors.muted} />
            <Text style={[styles.personName, p.status === "done" && { color: colors.onSurface }]} numberOfLines={1}>{p.name}</Text>
            <Text style={styles.sub}>{p.status === "done" ? (p.completed_at ? `Done ${formatDate(p.completed_at)}` : "Done") : "Not done yet"}</Text>
          </View>
        ))}
    </View>
  );
}


const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  chipRow: { flexGrow: 0, height: 56, backgroundColor: c.surface },
  chipContent: { paddingHorizontal: 16, gap: 8, alignItems: "center" },
  row: { flexDirection: "row", alignItems: "flex-start", gap: 12, backgroundColor: c.surface, borderRadius: 14, padding: 14, minHeight: 56 },
  title: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  doneText: { textDecorationLine: "line-through", color: c.muted },
  desc: { fontSize: 14, color: c.onSurfaceSecondary },
  sub: { fontSize: 13, color: c.muted },
  subRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2 },
  attach: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 32, alignSelf: "flex-start" },
  attachText: { fontSize: 14, fontWeight: "600", color: c.brandPrimary, flexShrink: 1 },
  collab: { fontSize: 13, color: c.brandPrimary, fontWeight: "600", flexShrink: 1 },
  progress: { marginTop: 6, gap: 6 },
  progressHead: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 32 },
  bar: { flex: 1, height: 8, borderRadius: 4, backgroundColor: c.surfaceTertiary, overflow: "hidden" },
  barFill: { height: 8, borderRadius: 4, backgroundColor: c.success },
  progressText: { fontSize: 13, fontWeight: "600", color: c.onSurface },
  personRow: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 28 },
  personName: { flex: 1, fontSize: 14, color: c.onSurfaceSecondary },
  delBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center", marginTop: -10, marginRight: -8 },
}));
