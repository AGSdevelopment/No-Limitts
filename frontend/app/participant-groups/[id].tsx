// One participant group: members (from the Support Team plus coordinator changes), group chat, announcements and tasks.
import { useState } from "react";
import { Pressable, RefreshControl, ScrollView, View } from "react-native";
import { Stack, router, useLocalSearchParams } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Text } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { ConfirmSheet, Sheet } from "@/src/components/participant-sheets";
import { Avatar, Button, Chip, ErrorState, Field, Ionicons, Loading, Pill, dmyToIso, isoToDmy } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function GroupDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const q = useQuery<any>({ queryKey: ["participant-group", id], queryFn: () => api(`/participant-groups/${id}`) });
  const [sheet, setSheet] = useState<"announce" | "task" | "add" | "delete" | null>(null);
  const [text, setText] = useState("");
  const [task, setTask] = useState({ title: "", description: "", due: "", kind: "action" });
  const [busy, setBusy] = useState(false);
  const [removeM, setRemoveM] = useState<any>(null);
  const staff = useQuery<any[]>({ queryKey: ["users"], queryFn: () => api("/users"), enabled: sheet === "add" });

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as any)?.message ?? "Couldn't load this group."} onRetry={q.refetch} />;
  const g = q.data;
  const memberIds = new Set(g.members.map((m: any) => m.user_id));

  const run = async (fn: () => Promise<any>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      toast(ok, "success");
      setSheet(null);
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const announce = () => {
    if (text.trim().length < 2) return toast("Write the announcement", "error");
    run(() => api(`/participant-groups/${id}/announce`, { method: "POST", body: { text } }), "Announcement sent").then(() => setText(""));
  };
  const allocate = () => {
    if (!task.title.trim()) return toast("Give the task a title", "error");
    const due = task.due.trim() ? dmyToIso(task.due) : "";
    if (task.due.trim() && !due) return toast("Enter the due date as DD-MM-YYYY", "error");
    run(() => api(`/participant-groups/${id}/tasks`, { method: "POST", body: { title: task.title, description: task.description, due_date: due, kind: task.kind } }),
      `Task sent to ${g.members.length} member${g.members.length === 1 ? "" : "s"}`).then(() => setTask({ title: "", description: "", due: "", kind: "action" }));
  };
  const members = (body: any, ok: string) => run(() => api(`/participant-groups/${id}/members`, { method: "PUT", body }), ok);

  return (
    <>
      <Stack.Screen options={{ title: g.name }} />
      <ScrollView style={styles.root} testID="group-screen" contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}>
        <Button label="Open group chat" icon="chatbubbles-outline" testID="group-chat"
          onPress={() => router.push({ pathname: "/chat/[id]", params: { id: g.conversation_id, name: g.name } })} />
        {g.can_manage && (
          <View style={styles.row}>
            <Button label="Announce" icon="megaphone-outline" variant="secondary" style={{ flex: 1 }} onPress={() => setSheet("announce")} testID="group-announce" />
            <Button label="Give a task" icon="checkbox-outline" variant="secondary" style={{ flex: 1 }} onPress={() => setSheet("task")} testID="group-task" />
          </View>
        )}

        <View style={styles.headRow}>
          <Text style={styles.section}>Members ({g.members.length})</Text>
          {g.can_manage && (
            <Pressable onPress={() => setSheet("add")} style={styles.link} testID="group-add-member">
              <Ionicons name="person-add-outline" size={16} color={colors.brandPrimary} />
              <Text style={styles.linkText}>Add</Text>
            </Pressable>
          )}
        </View>
        {g.members.map((m: any) => (
          <View key={m.user_id} style={styles.card} testID={`group-member-${m.user_id}`}>
            <Avatar name={m.name} picture={m.picture} size={36} />
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>{m.name}</Text>
              <Text style={styles.meta}>{m.from_team ? "Support Team" : "Added by a coordinator"}</Text>
            </View>
            {g.can_manage && (
              <Pressable onPress={() => setRemoveM(m)} hitSlop={8} style={styles.iconBtn}
                accessibilityLabel={`Remove ${m.name}`} testID={`group-remove-${m.user_id}`}>
                <Ionicons name="close-circle-outline" size={22} color={colors.muted} />
              </Pressable>
            )}
          </View>
        ))}
        {!g.members.length && <Text style={styles.meta}>No members yet. Approve Support Team tags or add people.</Text>}

        <Text style={styles.section}>Tasks</Text>
        {!g.tasks.length && <Text style={styles.meta}>No group tasks yet.</Text>}
        {g.tasks.map((t: any) => (
          <View key={t.task_group_id} style={[styles.card, { flexDirection: "column", alignItems: "stretch", gap: 4 }]} testID={`group-taskrow-${t.task_group_id}`}>
            <View style={styles.row}>
              <Text style={[styles.title, { flex: 1 }]}>{t.title}</Text>
              <Pill label={t.kind === "acknowledge" ? "Acknowledge" : "Action"} tone="muted" />
            </View>
            {!!t.description && <Text style={styles.meta}>{t.description}</Text>}
            <Text style={[styles.meta, t.overdue && { color: colors.errorText, fontWeight: "700" }]}>
              {t.due_date ? `Due ${isoToDmy(t.due_date)}${t.overdue ? " · overdue" : ""} · ` : ""}from {t.created_by}
            </Text>
            {g.can_manage ? (
              <>
                <Text style={styles.body}>{t.done.length} of {t.done.length + t.outstanding.length} done</Text>
                {!!t.outstanding.length && <Text style={styles.meta}>Waiting on: {t.outstanding.map((o: any) => o.name).join(", ")}</Text>}
              </>
            ) : (
              <Text style={styles.body}>{t.mine_done ? "You've done this ✓" : "Open in My tasks to tick it off"}</Text>
            )}
          </View>
        ))}
        {g.can_manage && <Button label="Delete group" icon="trash-outline" variant="ghost" onPress={() => setSheet("delete")} testID="group-delete" />}
      </ScrollView>

      <Sheet visible={sheet === "announce"} onClose={() => !busy && setSheet(null)} title="Announcement" sub="Posted in the group chat and sent as an alert to every member." testID="group-announce-sheet">
        <Field label="Message" value={text} onChangeText={setText} multiline testID="group-announce-input" />
        <Button label="Send announcement" icon="megaphone-outline" loading={busy} disabled={busy} onPress={announce} testID="group-announce-send" />
        <Button label="Cancel" variant="ghost" onPress={() => setSheet(null)} />
      </Sheet>

      <Sheet visible={sheet === "task"} onClose={() => !busy && setSheet(null)} title="Give a task to the group" sub="Every member gets their own copy and must tick it off. Tracked in Compliance." testID="group-task-sheet">
        <View style={styles.row}>
          <Chip label="Action required" selected={task.kind === "action"} onPress={() => setTask({ ...task, kind: "action" })} testID="group-task-action" />
          <Chip label="Acknowledge" selected={task.kind === "acknowledge"} onPress={() => setTask({ ...task, kind: "acknowledge" })} testID="group-task-ack" />
        </View>
        <Field label="Title" value={task.title} onChangeText={(v) => setTask({ ...task, title: v })} testID="group-task-title" />
        <Field label="Details (optional)" value={task.description} onChangeText={(v) => setTask({ ...task, description: v })} multiline testID="group-task-desc" />
        <Field label="Due date (optional)" value={task.due} onChangeText={(v) => setTask({ ...task, due: v })} placeholder="DD-MM-YYYY" testID="group-task-due" />
        <Button label="Send task" icon="send-outline" loading={busy} disabled={busy} onPress={allocate} testID="group-task-send" />
        <Button label="Cancel" variant="ghost" onPress={() => setSheet(null)} />
      </Sheet>

      <Sheet visible={sheet === "add"} onClose={() => !busy && setSheet(null)} title="Add to group" sub="Tap a person to add them." testID="group-add-sheet">
        {staff.isLoading ? <Loading /> : (
          <ScrollView style={{ maxHeight: 400 }} contentContainerStyle={styles.chips}>
            {(staff.data ?? []).filter((u) => !memberIds.has(u.user_id)).map((u) => (
              <Chip key={u.user_id} label={u.name} selected={false} onPress={() => !busy && members({ add_ids: [u.user_id] }, `${u.name} added`)} testID={`group-add-${u.user_id}`} />
            ))}
          </ScrollView>
        )}
        <Button label="Done" variant="ghost" onPress={() => setSheet(null)} />
      </Sheet>

      <ConfirmSheet visible={!!removeM} title={`Remove ${removeM?.name ?? ""}?`} sub="They leave the group chat and won't get new group tasks. You can add them back later."
        confirmLabel="Remove" busy={busy} onClose={() => setRemoveM(null)}
        onConfirm={() => members({ remove_ids: [removeM.user_id] }, `${removeM.name} removed from the group`).then(() => setRemoveM(null))} />

      <ConfirmSheet visible={sheet === "delete"} title={`Delete ${g.name}?`} sub="The group chat and any open group tasks are removed. Completed tasks stay on record."
        confirmLabel="Delete group" busy={busy} onClose={() => setSheet(null)}
        onConfirm={() => run(() => api(`/participant-groups/${id}`, { method: "DELETE" }), "Group deleted").then(() => router.replace("/participant-groups"))} />
    </>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  row: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  headRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 4 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  card: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: c.surface, borderRadius: 14, padding: 12, minHeight: 56 },
  section: { fontSize: 13, fontWeight: "700", color: c.muted, textTransform: "uppercase", marginTop: 4 },
  title: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  body: { fontSize: 14, color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
  link: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 44, paddingHorizontal: 6 },
  linkText: { fontSize: 14, fontWeight: "700", color: c.brandPrimary },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
}));
