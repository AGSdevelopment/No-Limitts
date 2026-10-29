// Caseload sheets: add a participant, assign Support Workers, and pick a case note form to write.
import { useEffect, useState } from "react";
import { FlatList, Modal, Pressable, ScrollView, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openLink } from "@/src/api";
import { Text, TextInput } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, ErrorState, Ionicons, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

function Sheet({ visible, onClose, title, sub, children, testID }: {
  visible: boolean; onClose: () => void; title: string; sub?: string; children: React.ReactNode; testID: string;
}) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior="padding" style={{ flex: 1 }}>
        <Pressable style={styles.scrim} onPress={onClose} />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID={testID}>
          <Text style={styles.title}>{title}</Text>
          {!!sub && <Text style={styles.sub}>{sub}</Text>}
          {children}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

export function ConfirmSheet({ visible, title, sub, confirmLabel, busy, onConfirm, onClose }: {
  visible: boolean; title: string; sub: string; confirmLabel: string; busy?: boolean; onConfirm: () => void; onClose: () => void;
}) {
  return (
    <Sheet visible={visible} onClose={onClose} title={title} sub={sub} testID="confirm-sheet">
      <Button label={confirmLabel} icon="trash-outline" variant="danger" loading={busy} disabled={busy} onPress={onConfirm} testID="confirm-sheet-yes" />
      <Button label="Cancel" variant="ghost" onPress={onClose} testID="confirm-sheet-cancel" />
    </Sheet>
  );
}

export function ImportResultSheet({ result, onClose }: { result: { added: any[]; updated: any[]; skipped: any[] } | null; onClose: () => void }) {
  const styles = useStyles();
  const unknown = [...(result?.added ?? []), ...(result?.updated ?? [])].filter((r) => r.unknown?.length);
  return (
    <Sheet visible={!!result} onClose={onClose} title="Import finished"
      sub={`${result?.added.length ?? 0} added · ${result?.updated.length ?? 0} updated · ${result?.skipped.length ?? 0} skipped`} testID="participants-import-result">
      <ScrollView style={{ maxHeight: 320 }} contentContainerStyle={{ gap: 6 }}>
        {unknown.map((r) => (
          <Text key={`u${r.row}`} style={styles.sub}>Row {r.row} ({r.name}): couldn&apos;t find Support Worker {r.unknown.join(", ")}</Text>
        ))}
        {(result?.skipped ?? []).map((r) => (
          <Text key={`s${r.row}`} style={styles.sub}>Row {r.row}: {r.reason}</Text>
        ))}
      </ScrollView>
      <Button label="Done" onPress={onClose} testID="participants-import-done" />
    </Sheet>
  );
}

export function AddParticipantSheet({ visible, onClose, onDone }: { visible: boolean; onClose: () => void; onDone: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      const p = await api<any>("/participants", { method: "POST", body: { name } });
      toast(`${p.name} added`, "success");
      setName("");
      onDone();
      onClose();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Sheet visible={visible} onClose={onClose} title="Add participant" sub="Use the same name you'll enter on case notes so their history links up." testID="add-participant-sheet">
      <TextInput value={name} onChangeText={setName} placeholder="Participant's full name" placeholderTextColor={colors.muted}
        style={styles.search} autoFocus testID="add-participant-name" />
      <Button label="Add participant" icon="person-add-outline" loading={saving} disabled={name.trim().length < 2} onPress={save} testID="add-participant-save" />
      <Button label="Cancel" variant="ghost" onPress={onClose} testID="add-participant-cancel" />
    </Sheet>
  );
}

export function AssignSheet({ participant, onClose, onDone }: { participant: any | null; onClose: () => void; onDone: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [picked, setPicked] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const q = useQuery<any[]>({ queryKey: ["users"], queryFn: () => api("/users"), enabled: !!participant });
  useEffect(() => {
    setPicked((participant?.assigned ?? []).map((a: any) => a.user_id));
    setSearch("");
  }, [participant]);
  const workers = (q.data ?? []).filter((u) => u.user_type === "support_worker" && u.name?.toLowerCase().includes(search.trim().toLowerCase()));
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const save = async () => {
    setSaving(true);
    try {
      await api(`/participants/${participant.participant_id}/assign`, { method: "PUT", body: { user_ids: picked } });
      toast(`Support Workers updated for ${participant.name}`, "success");
      onDone();
      onClose();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Sheet visible={!!participant} onClose={onClose} title={`Assign Support Workers`}
      sub={`Only ticked Support Workers can see ${participant?.name ?? ""} and their Support Worker case notes.`} testID="assign-sheet">
      <TextInput value={search} onChangeText={setSearch} placeholder="Search Support Workers" placeholderTextColor={colors.muted}
        style={styles.search} testID="assign-search" />
      {q.isLoading ? <Loading /> : (
        <FlatList
          data={workers}
          keyExtractor={(u) => u.user_id}
          style={{ maxHeight: 340 }}
          keyboardShouldPersistTaps="handled"
          ListEmptyComponent={<Text style={styles.sub}>No Support Workers found.</Text>}
          renderItem={({ item }) => {
            const on = picked.includes(item.user_id);
            return (
              <Pressable onPress={() => toggle(item.user_id)} style={styles.row} testID={`assign-user-${item.user_id}`}
                accessibilityRole="checkbox" accessibilityState={{ checked: on }}>
                <Avatar name={item.name} picture={item.picture} size={36} />
                <Text style={[styles.name, { flex: 1 }]}>{item.name}</Text>
                <Ionicons name={on ? "checkbox" : "square-outline"} size={24} color={on ? colors.brandPrimary : colors.muted} />
              </Pressable>
            );
          }}
        />
      )}
      <Button label={`Save (${picked.length} assigned)`} icon="checkmark-outline" loading={saving} onPress={save} testID="assign-save" />
      <Button label="Cancel" variant="ghost" onPress={onClose} testID="assign-cancel" />
    </Sheet>
  );
}

export function CaseFormsSheet({ participant, onClose }: { participant: string | null; onClose: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const q = useQuery<any[]>({
    queryKey: ["caseload-forms", participant],
    queryFn: () => api(`/caseload/forms?participant=${encodeURIComponent(participant ?? "")}`),
    enabled: !!participant,
  });
  return (
    <Sheet visible={!!participant} onClose={onClose} title="Write a case note" sub={`Choose any Day-to-Day form. Where it says "Details filled in", ${participant ?? ""}'s name and yours are added for you.`} testID="case-forms-sheet">
      {q.isLoading ? <Loading /> : q.isError ? (
        <ErrorState message={(q.error as any)?.message ?? "Couldn't load forms"} onRetry={q.refetch} />
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(f) => f.url}
          style={{ maxHeight: 380 }}
          renderItem={({ item }) => (
            <Pressable onPress={() => { onClose(); openLink(item.url); }} style={styles.row} testID={`case-form-${item.title}`}>
              <Ionicons name={item.kind === "coordinator" ? "briefcase-outline" : "document-text-outline"} size={22} color={colors.brandPrimary} />
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.title}</Text>
                {item.prefilled && <Text style={styles.sub}>Details filled in</Text>}
              </View>
              <Ionicons name="open-outline" size={18} color={colors.muted} />
            </Pressable>
          )}
        />
      )}
      <Button label="Cancel" variant="ghost" onPress={onClose} testID="case-forms-cancel" />
    </Sheet>
  );
}

const useStyles = makeStyles((c) => ({
  scrim: { flex: 1, backgroundColor: c.scrim },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, gap: 10 },
  title: { fontSize: 19, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted, lineHeight: 18 },
  search: { minHeight: 44, borderRadius: 12, backgroundColor: c.surfaceSecondary, paddingHorizontal: 14, fontSize: 15, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", gap: 12, minHeight: 52, paddingVertical: 4 },
  name: { fontSize: 15, fontWeight: "600", color: c.onSurface },
}));
