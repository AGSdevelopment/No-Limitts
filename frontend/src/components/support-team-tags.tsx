// Team Directory: tag a Support Worker to a participant's Support Team (approved by Service Coordinators).
import { useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/src/api";
import { Text, TextInput } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Sheet } from "@/src/components/participant-sheets";
import { Button, Ionicons, Pill } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export function SupportTeamTags({ member, onClose }: { member: { user_id: string; name: string } | null; onClose: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useQuery<any>({ queryKey: ["team-tags", member?.user_id], queryFn: () => api(`/support-team/tags/${member!.user_id}`), enabled: !!member });
  const names = useQuery<any[]>({ queryKey: ["pm-participants"], queryFn: () => api("/pm/participants"), enabled: !!member });
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState("");
  const taken = new Set([...(q.data?.approved ?? []).map((p: any) => p.participant_id), ...(q.data?.pending ?? []).map((p: any) => p.participant_id)]);
  const matches = search.trim().length >= 2
    ? (names.data ?? []).filter((p) => !taken.has(p.participant_id) && p.name.toLowerCase().includes(search.trim().toLowerCase())).slice(0, 6)
    : [];

  const tag = async (pid: string) => {
    setBusy(pid);
    try {
      const r = await api<any>("/support-team/tags", { method: "POST", body: { user_id: member!.user_id, participant_id: pid } });
      toast(r.status === "approved" ? "Added to the Support Team" : "Tag sent to Service Coordinators for approval", "success");
      setSearch("");
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy("");
    }
  };

  return (
    <Sheet visible={!!member} onClose={onClose} title={`${member?.name ?? ""} · Participant tags`}
      sub="Approved tags put them on that participant's Support Team, so they can be rostered." testID="team-tags-sheet">
      <ScrollView style={{ maxHeight: 460 }} contentContainerStyle={{ gap: 8 }} keyboardShouldPersistTaps="handled">
        {(q.data?.approved ?? []).map((p: any) => (
          <View key={p.participant_id} style={styles.row} testID={`team-tag-${p.participant_id}`}>
            <Ionicons name="checkmark-circle" size={18} color={colors.successText} />
            <Text style={[styles.body, { flex: 1 }]}>{p.name}</Text>
            <Pill label="Approved" tone="brand" />
          </View>
        ))}
        {(q.data?.pending ?? []).map((p: any) => (
          <View key={p.request_id} style={styles.row} testID={`team-tag-pending-${p.participant_id}`}>
            <Ionicons name="time-outline" size={18} color={colors.warningText} />
            <Text style={[styles.body, { flex: 1 }]}>{p.participant_name}</Text>
            <Pill label="Awaiting approval" tone="accent" />
          </View>
        ))}
        {!q.data?.approved?.length && !q.data?.pending?.length && <Text style={styles.meta}>No participant tags yet.</Text>}
        {q.data?.can_request && (
          <>
            <TextInput value={search} onChangeText={setSearch} placeholder="Search a participant's name to tag" placeholderTextColor={colors.muted}
              style={styles.input} testID="team-tags-search" />
            {matches.map((p) => (
              <Pressable key={p.participant_id} onPress={() => tag(p.participant_id)} disabled={!!busy} style={styles.pick} testID={`team-tags-add-${p.participant_id}`}>
                <Ionicons name="pricetag-outline" size={18} color={colors.brandPrimary} />
                <Text style={[styles.body, { flex: 1 }]}>{p.name}</Text>
                <Text style={styles.add}>{busy === p.participant_id ? "Adding…" : "Tag"}</Text>
              </Pressable>
            ))}
          </>
        )}
        <Button label="Done" variant="ghost" onPress={onClose} />
      </ScrollView>
    </Sheet>
  );
}

const useStyles = makeStyles((c) => ({
  row: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 40 },
  body: { fontSize: 15, color: c.onSurface },
  meta: { fontSize: 13, color: c.muted },
  input: { minHeight: 48, borderRadius: 12, paddingHorizontal: 14, fontSize: 15, color: c.onSurface, backgroundColor: c.surfaceSecondary },
  pick: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 48, paddingHorizontal: 8, borderRadius: 12, backgroundColor: c.brandTertiary },
  add: { fontSize: 14, fontWeight: "700", color: c.brandPrimary },
}));
