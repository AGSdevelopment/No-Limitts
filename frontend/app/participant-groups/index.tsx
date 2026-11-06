// Participant Groups: each participant's Support Team as a group (chat, announcements, tasks). Coordinators create and manage.
import { useState } from "react";
import { FlatList, Pressable, RefreshControl, View } from "react-native";
import { router } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Text } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Sheet } from "@/src/components/participant-sheets";
import { Button, Chip, EmptyState, ErrorState, Ionicons, Loading, Pill } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function ParticipantGroups() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const q = useQuery<any>({ queryKey: ["participant-groups"], queryFn: () => api("/participant-groups") });
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState("");
  const people = useQuery<any[]>({ queryKey: ["pm-participants"], queryFn: () => api("/pm/participants"), enabled: picking });

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as any)?.message ?? "Couldn't load groups."} onRetry={q.refetch} />;
  const { groups, can_manage } = q.data;
  const taken = new Set(groups.map((g: any) => g.participant_id));
  const free = (people.data ?? []).filter((p) => !taken.has(p.participant_id));

  const create = async (pid: string) => {
    setBusy(pid);
    try {
      const g = await api<any>("/participant-groups", { method: "POST", body: { participant_id: pid } });
      toast(`${g.name} created with ${g.members.length} member${g.members.length === 1 ? "" : "s"}`, "success");
      setPicking(false);
      q.refetch();
      router.push(`/participant-groups/${g.group_id}`);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy("");
    }
  };

  return (
    <>
      <FlatList
        style={styles.root}
        testID="groups-screen"
        data={groups}
        keyExtractor={(g: any) => g.group_id}
        contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}
        ListHeaderComponent={can_manage ? (
          <View style={{ gap: 8, marginBottom: 4 }}>
            <Button label="New participant group" icon="people-outline" onPress={() => setPicking(true)} testID="groups-new" />
            <Button label="Group task tracker" icon="checkmark-done-outline" variant="secondary" onPress={() => router.push("/participant-groups/compliance")} testID="groups-tracker" />
          </View>
        ) : <Text style={styles.meta}>Support Team groups you&apos;re part of.</Text>}
        ListEmptyComponent={<EmptyState icon="people-outline" title="No participant groups yet"
          subtitle={can_manage ? "Create one to message and give tasks to a participant's whole Support Team." : "You'll see a group here once a coordinator adds you."} />}
        renderItem={({ item: g }) => (
          <Pressable onPress={() => router.push(`/participant-groups/${g.group_id}`)} style={styles.card} testID={`group-${g.group_id}`}>
            <View style={styles.icon}><Ionicons name="people" size={20} color={colors.brandPrimary} /></View>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.title}>{g.name}</Text>
              <Text style={styles.meta} numberOfLines={1}>{g.members.length} member{g.members.length === 1 ? "" : "s"} · {g.members.map((m: any) => m.name.split(" ")[0]).join(", ") || "none yet"}</Text>
            </View>
            {g.overdue_tasks > 0 ? <Pill label={`${g.overdue_tasks} overdue`} tone="accent" /> : g.open_tasks > 0 ? <Pill label={`${g.open_tasks} open`} tone="muted" /> : null}
            <Ionicons name="chevron-forward" size={18} color={colors.muted} />
          </Pressable>
        )}
      />
      <Sheet visible={picking} onClose={() => setPicking(false)} title="Choose a participant" sub="Their approved Support Team joins automatically. You can add or remove people afterwards." testID="groups-pick">
        {people.isLoading ? <Loading /> : !free.length ? <Text style={styles.meta}>Every participant already has a group.</Text> : (
          <View style={styles.chips}>
            {free.map((p) => <Chip key={p.participant_id} label={busy === p.participant_id ? "Creating…" : p.name} selected={false} onPress={() => !busy && create(p.participant_id)} testID={`groups-pick-${p.participant_id}`} />)}
          </View>
        )}
        <Button label="Cancel" variant="ghost" onPress={() => setPicking(false)} />
      </Sheet>
    </>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  card: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: c.surface, borderRadius: 14, padding: 14, minHeight: 64 },
  icon: { width: 40, height: 40, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  title: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
}));
