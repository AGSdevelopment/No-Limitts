import { useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, View } from "react-native";
import { Text } from "@/src/components/text";
import * as DocumentPicker from "expo-document-picker";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, Field, Ionicons, timeAgo } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";
import { uploadForm } from "@/src/utils/upload";

/** Admin: who has / hasn't acknowledged a policy, with a one-tap reminder. */
export function AckTrackerSheet({ policyId, visible, onClose }: { policyId: string; visible: boolean; onClose: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const q = useQuery<any>({ queryKey: ["policy-acks", policyId], queryFn: () => api(`/policies/${policyId}/acks`), enabled: visible });

  const remind = async () => {
    setBusy(true);
    try {
      const r = await api(`/policies/${policyId}/remind`, { method: "POST" });
      toast(`Reminder sent to ${r.reminded} ${r.reminded === 1 ? "person" : "people"}`);
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const d = q.data;
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID="ack-tracker-sheet">
        <View style={styles.head}>
          <Text style={styles.title}>Acknowledgements</Text>
          <Pressable onPress={onClose} hitSlop={10} style={styles.iconBtn} testID="ack-tracker-close">
            <Ionicons name="close" size={24} color={colors.onSurface} />
          </Pressable>
        </View>
        {q.isLoading || !d ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 32 }} />
        ) : (
          <>
            <Text style={styles.summary} testID="ack-tracker-summary">
              {d.acknowledged.length} of {d.acknowledged.length + d.pending.length} staff have acknowledged version {d.version}
            </Text>
            {d.pending.length > 0 && (
              <Button
                label={`Remind ${d.pending.length} ${d.pending.length === 1 ? "person" : "people"}`}
                icon="notifications-outline"
                loading={busy}
                onPress={remind}
                testID="ack-remind-button"
              />
            )}
            {!!d.last_reminded_at && <Text style={styles.meta}>Last reminder sent {timeAgo(d.last_reminded_at)}</Text>}
            <ScrollView contentContainerStyle={{ paddingBottom: 16 }} style={{ marginTop: 8 }}>
              <Text style={styles.section}>Not yet acknowledged ({d.pending.length})</Text>
              {d.pending.length === 0 && <Text style={styles.meta}>Everyone is up to date.</Text>}
              {d.pending.map((u: any) => (
                <View key={u.user_id} style={styles.row} testID={`ack-pending-${u.user_id}`}>
                  <Avatar name={u.name} picture={u.picture} size={32} />
                  <Text style={styles.name}>{u.name}</Text>
                  <Ionicons name="time-outline" size={18} color={colors.warningText} />
                </View>
              ))}
              <Text style={[styles.section, { marginTop: 16 }]}>Acknowledged ({d.acknowledged.length})</Text>
              {d.acknowledged.map((u: any) => (
                <View key={u.user_id} style={styles.row} testID={`ack-done-${u.user_id}`}>
                  <Avatar name={u.name} picture={u.picture} size={32} />
                  <Text style={styles.name}>{u.name}</Text>
                  <Ionicons name="checkmark-circle" size={18} color={colors.successText} />
                </View>
              ))}
            </ScrollView>
          </>
        )}
      </View>
    </Modal>
  );
}

type Picked = { uri: string; name: string; mimeType?: string };

/** Admin: replace a policy with a new version; staff must re-acknowledge. */
export function NewVersionSheet({ policy, visible, onClose }: { policy: any; visible: boolean; onClose: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const qc = useQueryClient();
  const [file, setFile] = useState<Picked | null>(null);
  const [note, setNote] = useState("");
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = async () => {
    const r = await DocumentPicker.getDocumentAsync({ type: ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"], copyToCacheDirectory: true });
    if (!r.canceled && r.assets?.[0]) {
      const a = r.assets[0];
      setFile({ uri: a.uri, name: a.name, mimeType: a.mimeType ?? undefined });
    }
  };

  const save = async () => {
    setError(null);
    if (!file && !content.trim()) return setError("Upload the new document or paste the updated text.");
    setSaving(true);
    try {
      const res = await uploadForm(`${API_URL}/policies/${policy.policy_id}/version`, {
        headers: authHeaders(),
        fields: { change_note: note.trim(), content: content.trim() },
        files: file ? { file } : {},
      });
      const b = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof b.detail === "string" ? b.detail : "Couldn't save the new version");
      await qc.invalidateQueries({ queryKey: ["policies"] });
      qc.invalidateQueries({ queryKey: ["policy-acks", policy.policy_id] });
      toast(`Version ${b.version} published. Staff have been asked to re-acknowledge.`);
      setFile(null);
      setNote("");
      setContent("");
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <KeyboardAwareScrollView style={styles.sheetBg} contentContainerStyle={{ padding: 20, paddingBottom: insets.bottom + 24 }} keyboardShouldPersistTaps="handled" bottomOffset={24} testID="new-version-sheet">
        <View style={styles.head}>
          <Text style={styles.title}>New version</Text>
          <Pressable onPress={onClose} hitSlop={10} style={styles.iconBtn} testID="new-version-close">
            <Ionicons name="close" size={24} color={colors.onSurface} />
          </Pressable>
        </View>
        <Text style={styles.summary}>
          Replaces “{policy.title}” (version {policy.version}). Everyone will be asked to read and acknowledge it again.
        </Text>
        {file ? (
          <View style={styles.fileCard} testID="new-version-file">
            <Ionicons name="document-text" size={22} color={colors.brandPrimary} />
            <Text style={[styles.name, { flex: 1 }]} numberOfLines={1}>{file.name}</Text>
            <Pressable onPress={() => setFile(null)} hitSlop={8} style={styles.iconBtn} testID="new-version-file-remove">
              <Ionicons name="close-circle" size={22} color={colors.muted} />
            </Pressable>
          </View>
        ) : (
          <Button label="Upload new document (PDF or Word)" variant="secondary" icon="cloud-upload-outline" onPress={pick} testID="new-version-pick" />
        )}
        <View style={{ height: 16 }} />
        <Field label="What changed? (shown to staff)" value={note} onChangeText={setNote} placeholder="e.g. Updated mileage rates" testID="new-version-note" />
        <Field label={file ? "Updated text (optional, read from the PDF if empty)" : "Updated text"} value={content} onChangeText={setContent} multiline placeholder="Paste the new policy text" testID="new-version-content" />
        {error && <Text style={styles.error} testID="new-version-error">{error}</Text>}
        <Button label="Publish new version" icon="checkmark" loading={saving} onPress={save} testID="new-version-save" />
      </KeyboardAwareScrollView>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  sheet: { flex: 1, backgroundColor: c.surface, padding: 20, gap: 8 },
  sheetBg: { flex: 1, backgroundColor: c.surface },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  title: { fontSize: 20, fontWeight: "700", color: c.onSurface },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  summary: { fontSize: 15, color: c.onSurfaceSecondary, lineHeight: 21, marginBottom: 12 },
  meta: { fontSize: 13, color: c.muted, marginTop: 4 },
  section: { fontSize: 13, fontWeight: "600", color: c.muted, textTransform: "uppercase", marginBottom: 8, marginTop: 8 },
  row: { flexDirection: "row", alignItems: "center", gap: 12, minHeight: 48, borderBottomWidth: 0.5, borderBottomColor: c.divider },
  name: { flex: 1, fontSize: 15, color: c.onSurface },
  fileCard: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.brandTertiary, borderRadius: 14, paddingLeft: 14, minHeight: 56 },
  error: { fontSize: 14, color: c.errorText, marginBottom: 12 },
}));
