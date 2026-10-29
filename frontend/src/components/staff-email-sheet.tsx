// Pick No Limitts staff to email a participant's plan review summary to.
import { useState } from "react";
import { FlatList, Modal, Pressable, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Text, TextInput } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, Ionicons, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export function StaffEmailSheet({ participant, onClose }: { participant: string | null; onClose: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const [picked, setPicked] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [sending, setSending] = useState(false);
  const q = useQuery<any[]>({ queryKey: ["users"], queryFn: () => api("/users"), enabled: !!participant });
  const people = (q.data ?? []).filter((u) => u.name?.toLowerCase().includes(search.trim().toLowerCase()));
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= 15 ? p : [...p, id]));

  const close = () => {
    setPicked([]);
    setSearch("");
    onClose();
  };
  const send = async () => {
    setSending(true);
    try {
      const r = await api<any>("/caseload/summary/email", { method: "POST", body: { name: participant, user_ids: picked } });
      toast(`Emailed to ${r.sent.join(", ")}`, "success");
      close();
    } catch (e: any) {
      toast(e.message ?? "Couldn't send the email", "error");
    } finally {
      setSending(false);
    }
  };

  return (
    <Modal visible={!!participant} transparent animationType="slide" onRequestClose={close}>
      <KeyboardAvoidingView behavior="padding" style={{ flex: 1 }}>
      <Pressable style={styles.scrim} onPress={close} />
      <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID="caseload-email-sheet">
        <Text style={styles.title}>Email summary</Text>
        <Text style={styles.sub}>Choose who in the support team gets {participant}&apos;s plan review PDF. Each person gets a private link that works for 7 days.</Text>
        <TextInput value={search} onChangeText={setSearch} placeholder="Search staff" placeholderTextColor={colors.muted}
          style={styles.search} testID="caseload-email-search" />
        {q.isLoading ? <Loading /> : (
          <FlatList
            data={people}
            keyExtractor={(u) => u.user_id}
            style={{ maxHeight: 340 }}
            keyboardShouldPersistTaps="handled"
            renderItem={({ item }) => {
              const on = picked.includes(item.user_id);
              return (
                <Pressable onPress={() => toggle(item.user_id)} style={styles.row} testID={`caseload-email-user-${item.user_id}`}
                  accessibilityRole="checkbox" accessibilityState={{ checked: on }}>
                  <Avatar name={item.name} picture={item.picture} size={36} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.name}>{item.name}</Text>
                    {!!item.job_title && <Text style={styles.sub}>{item.job_title}</Text>}
                  </View>
                  <Ionicons name={on ? "checkbox" : "square-outline"} size={24} color={on ? colors.brandPrimary : colors.muted} />
                </Pressable>
              );
            }}
          />
        )}
        <Button label={sending ? "Sending…" : picked.length ? `Send to ${picked.length}` : "Choose people"} icon="mail-outline"
          loading={sending} disabled={!picked.length} onPress={send} testID="caseload-email-send" />
        <Button label="Cancel" variant="ghost" onPress={close} testID="caseload-email-cancel" />
      </View>
      </KeyboardAvoidingView>
    </Modal>
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
