import { useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useRouter } from "expo-router";
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import * as Haptics from "expo-haptics";
import { useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, authHeaders } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, Chip, Field, IconBox, Ionicons, isoDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";
import { uploadForm } from "@/src/utils/upload";

type Picked = { uri: string; name: string; mimeType?: string };
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function addYears(n: number) {
  const d = new Date();
  d.setFullYear(d.getFullYear() + n);
  return isoDate(d);
}

export default function UploadCertificate() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [file, setFile] = useState<Picked | null>(null);
  const [title, setTitle] = useState("");
  const [issuer, setIssuer] = useState("");
  const [issueDate, setIssueDate] = useState(isoDate(new Date()));
  const [expiry, setExpiry] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);

  const autoFill = async () => {
    if (!file) return;
    setError(null);
    setReading(true);
    try {
      const res = await uploadForm(`${API_URL}/ai/extract-certificate`, { headers: authHeaders(), files: { file } });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Couldn't read the certificate");
      if (body.title) setTitle(body.title);
      if (body.issuer) setIssuer(body.issuer);
      if (body.issue_date) setIssueDate(body.issue_date);
      if (body.expiry_date) setExpiry(body.expiry_date);
      toast(body.expiry_date ? "Details filled in. Please check them." : "Some details couldn't be read. Please check.", body.expiry_date ? "success" : "info");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setReading(false);
    }
  };

  const pickDoc = async () => {
    const r = await DocumentPicker.getDocumentAsync({ type: ["application/pdf", "image/*"], copyToCacheDirectory: true });
    if (!r.canceled && r.assets?.[0]) {
      const a = r.assets[0];
      setFile({ uri: a.uri, name: a.name, mimeType: a.mimeType ?? undefined });
    }
  };
  const pickPhoto = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7 });
    if (!r.canceled && r.assets?.[0]) {
      const a = r.assets[0];
      setFile({ uri: a.uri, name: a.fileName ?? "certificate.jpg", mimeType: a.mimeType ?? "image/jpeg" });
    }
  };

  const submit = async () => {
    setError(null);
    if (!file) return setError("Please attach the certificate file.");
    if (!title.trim()) return setError("Please enter the certificate name.");
    if (!DATE_RE.test(expiry)) return setError("Expiry date must be in YYYY-MM-DD format.");
    if (issueDate && !DATE_RE.test(issueDate)) return setError("Issue date must be in YYYY-MM-DD format.");
    setSaving(true);
    try {
      const res = await uploadForm(`${API_URL}/certificates`, {
        headers: authHeaders(),
        fields: { title: title.trim(), issuer: issuer.trim(), issue_date: issueDate, expiry_date: expiry },
        files: { file },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(typeof body.detail === "string" ? body.detail : "Upload failed");
      }
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      qc.invalidateQueries({ queryKey: ["certificates"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast("Certificate uploaded");
      router.back();
    } catch (e: any) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <KeyboardAwareScrollView
      style={styles.root}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 24 }}
      keyboardShouldPersistTaps="handled"
      bottomOffset={24}
      testID="upload-certificate-screen"
    >
      {file ? (
        <View style={styles.fileCard} testID="upload-selected-file">
          <IconBox name={file.mimeType?.includes("pdf") ? "document-text" : "image"} size={44} />
          <Text style={styles.fileName} numberOfLines={2}>{file.name}</Text>
          <Pressable testID="upload-remove-file" hitSlop={10} onPress={() => setFile(null)} style={styles.iconBtn}>
            <Ionicons name="close-circle" size={22} color={colors.muted} />
          </Pressable>
        </View>
      ) : (
        <View style={styles.pickRow}>
          <Pressable testID="upload-pick-document" onPress={pickDoc} style={({ pressed }) => [styles.pick, pressed && { opacity: 0.7 }]}>
            <Ionicons name="document-attach-outline" size={28} color={colors.brandPrimary} />
            <Text style={styles.pickText}>Choose file</Text>
            <Text style={styles.pickSub}>PDF or image</Text>
          </Pressable>
          <Pressable testID="upload-pick-photo" onPress={pickPhoto} style={({ pressed }) => [styles.pick, pressed && { opacity: 0.7 }]}>
            <Ionicons name="images-outline" size={28} color={colors.brandPrimary} />
            <Text style={styles.pickText}>From photos</Text>
            <Text style={styles.pickSub}>Photo of certificate</Text>
          </Pressable>
        </View>
      )}

      {file && (
        <Button
          label={reading ? "Reading certificate…" : "Auto-fill details with AI"}
          icon="sparkles-outline"
          variant="secondary"
          loading={reading}
          onPress={autoFill}
          style={{ marginBottom: 20 }}
          testID="upload-ai-autofill-button"
        />
      )}

      <Field label="Certificate name" value={title} onChangeText={setTitle} placeholder="e.g. First Aid at Work" testID="upload-title-input" />
      <Field label="Issued by (optional)" value={issuer} onChangeText={setIssuer} placeholder="e.g. St John Ambulance" testID="upload-issuer-input" />
      <Field label="Issue date (YYYY-MM-DD)" value={issueDate} onChangeText={setIssueDate} placeholder="2026-01-15" autoCapitalize="none" testID="upload-issue-date-input" />
      <Field label="Expiry date (YYYY-MM-DD)" value={expiry} onChangeText={setExpiry} placeholder="2027-01-15" autoCapitalize="none" testID="upload-expiry-date-input" />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }} style={{ marginTop: -4, marginBottom: 20 }}>
        {[1, 2, 3, 5].map((n) => (
          <Chip key={n} label={`+${n} year${n > 1 ? "s" : ""}`} selected={expiry === addYears(n)} onPress={() => setExpiry(addYears(n))} testID={`upload-expiry-quick-${n}`} />
        ))}
      </ScrollView>
      <Text style={styles.hint}>We&apos;ll remind you in the app and by email 30 days before it expires.</Text>
      {error && <Text style={styles.error} testID="upload-error">{error}</Text>}
      <Button label="Upload certificate" icon="cloud-upload-outline" loading={saving} onPress={submit} testID="upload-submit-button" />
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  pickRow: { flexDirection: "row", gap: 12, marginBottom: 20 },
  pick: { flex: 1, borderWidth: 1.5, borderStyle: "dashed", borderColor: c.borderStrong, borderRadius: 16, padding: 20, alignItems: "center", gap: 4, backgroundColor: c.brandTertiary },
  pickText: { fontSize: 15, fontWeight: "600", color: c.onSurface, marginTop: 4 },
  pickSub: { fontSize: 12, color: c.muted },
  fileCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, borderRadius: 16, backgroundColor: c.brandTertiary, marginBottom: 20 },
  fileName: { flex: 1, fontSize: 15, fontWeight: "600", color: c.onSurface },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  hint: { fontSize: 13, color: c.muted, marginBottom: 16, lineHeight: 18 },
  error: { fontSize: 14, color: c.errorText, marginBottom: 12 },
}));
