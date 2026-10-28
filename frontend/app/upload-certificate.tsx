import { useState } from "react";
import { Linking, Modal, Platform, Pressable, ScrollView, Switch, Text, View } from "react-native";
import { Stack, useRouter } from "expo-router";
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import * as Haptics from "expo-haptics";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, Chip, Field, IconBox, Ionicons, dmyDate, dmyToIso, isoToDmy } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";
import { uploadForm } from "@/src/utils/upload";

type Picked = { uri: string; name: string; mimeType?: string };
const DMY_HINT = "DD-MM-YYYY";
const CPD_TYPES = ["Course", "Webinar", "Case Study", "Resource link"];
const SPACES = [
  { key: "therapist", label: "Therapist Resources" },
  { key: "participant", label: "Participant Resources" },
];

function addYears(n: number) {
  const d = new Date();
  d.setFullYear(d.getFullYear() + n);
  return dmyDate(d);
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
  const [issueDate, setIssueDate] = useState(dmyDate(new Date()));
  const [expiry, setExpiry] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);

  const [camSheet, setCamSheet] = useState<null | "ask" | "settings">(null);
  const [countCpd, setCountCpd] = useState(false);
  const [cpdHours, setCpdHours] = useState("");
  const [shareCpd, setShareCpd] = useState(false);
  const [shareType, setShareType] = useState("");
  const [spaces, setSpaces] = useState<string[]>([]);
  const toggleSpace = (k: string) => setSpaces((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]));
  const [mode, setMode] = useState<"certificate" | "resource">("certificate");

  const submitResource = async () => {
    if (!file) return setError("Please attach the file to share.");
    if (!title.trim()) return setError("Please enter a title.");
    const h = parseFloat(cpdHours.replace(",", "."));
    if (countCpd && (!h || h <= 0)) return setError("Enter how many CPD hours were completed.");
    if (shareCpd && !shareType) return setError("Choose whether it's a Course, Webinar, Case Study or Resource link.");
    if (!shareCpd && !spaces.length && !countCpd) return setError("Choose at least one place to add it.");
    setSaving(true);
    try {
      const res = await uploadForm(`${API_URL}/resources/upload`, {
        headers: authHeaders(),
        fields: { title: title.trim(), provider: issuer.trim(), cpd_hours: countCpd ? String(h) : "", share_cpd: shareCpd ? shareType : "", drive_spaces: spaces.join(",") },
        files: { file },
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Upload failed");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      qc.invalidateQueries({ queryKey: ["cpd"] });
      qc.invalidateQueries({ queryKey: ["cpd-resources"] });
      const done = [body.cpd_log_id && "My CPD", body.cpd_resource_id && "CPD Resources",
        ...Object.entries(body.drive ?? {}).filter(([, v]) => v === "added").map(([k]) => SPACES.find((x) => x.key === k)?.label)].filter(Boolean);
      const failed = Object.entries(body.drive ?? {}).filter(([, v]) => v !== "added").map(([k]) => SPACES.find((x) => x.key === k)?.label);
      toast(failed.length ? `Shared, but couldn't add it to ${failed.join(" and ")}.` : `Shared to ${done.join(", ")}`, failed.length ? "info" : "success");
      if (router.canGoBack()) router.back();
      else router.replace("/(tabs)");
    } catch (e: any) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };
  const drive = useQuery<any>({ queryKey: ["drive-status"], queryFn: () => api("/integrations/google-drive/status") });

  const autoFill = async (target: Picked | null = file) => {
    if (!target) return;
    setError(null);
    setReading(true);
    try {
      const res = await uploadForm(`${API_URL}/ai/extract-certificate`, { headers: authHeaders(), files: { file: target } });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Couldn't read the certificate");
      if (body.title) setTitle(body.title);
      if (body.issuer) setIssuer(body.issuer);
      if (body.issue_date) setIssueDate(isoToDmy(body.issue_date));
      if (body.expiry_date) setExpiry(isoToDmy(body.expiry_date));
      toast(body.expiry_date ? "Details filled in. Please check them." : "Some details couldn't be read. Please check.", body.expiry_date ? "success" : "info");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setReading(false);
    }
  };

  const pickDoc = async () => {
    const r = await DocumentPicker.getDocumentAsync({ type: mode === "resource" ? "*/*" : ["application/pdf", "image/*"], copyToCacheDirectory: true });
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

  const launchCamera = async () => {
    setCamSheet(null);
    const r = await ImagePicker.launchCameraAsync({ mediaTypes: ["images"], quality: 0.7 });
    if (!r.canceled && r.assets?.[0]) {
      const a = r.assets[0];
      const picked = { uri: a.uri, name: a.fileName ?? "certificate-photo.jpg", mimeType: a.mimeType ?? "image/jpeg" };
      setFile(picked);
      if (mode === "certificate") autoFill(picked);
    }
  };
  const takePhoto = async () => {
    if (Platform.OS === "web") return launchCamera();
    const perm = await ImagePicker.getCameraPermissionsAsync();
    if (perm.granted) return launchCamera();
    setCamSheet(perm.status === "undetermined" || perm.canAskAgain ? "ask" : "settings");
  };
  const requestCamera = async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (perm.granted) return launchCamera();
    setCamSheet(perm.canAskAgain ? null : "settings");
    if (perm.canAskAgain) toast("Camera access is needed to take a photo. You can still choose a file.", "info");
  };

  const submit = async () => {
    setError(null);
    if (mode === "resource") return submitResource();
    if (!file) return setError("Please attach the certificate file.");
    if (!title.trim()) return setError("Please enter the certificate name.");
    const expiryIso = dmyToIso(expiry);
    const issueIso = issueDate ? dmyToIso(issueDate) : "";
    if (!expiryIso) return setError(`Expiry date must be in ${DMY_HINT} format.`);
    if (issueIso === null) return setError(`Issue date must be in ${DMY_HINT} format.`);
    const h = parseFloat(cpdHours.replace(",", "."));
    if (countCpd && (!h || h <= 0)) return setError("Enter how many CPD hours were completed.");
    if (shareCpd && !shareType) return setError("Choose whether it's a Course, Webinar, Case Study or Resource link.");
    setSaving(true);
    try {
      const res = await uploadForm(`${API_URL}/certificates`, {
        headers: authHeaders(),
        fields: {
          title: title.trim(), issuer: issuer.trim(), issue_date: issueIso, expiry_date: expiryIso, cpd_hours: countCpd ? String(h) : "",
          share_cpd: shareCpd ? shareType : "", drive_spaces: spaces.join(","),
        },
        files: { file },
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Upload failed");
      }
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      qc.invalidateQueries({ queryKey: ["certificates"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["cpd"] });
      qc.invalidateQueries({ queryKey: ["cpd-resources"] });
      const done = [countCpd && "My CPD", body.cpd_resource_id && "CPD Resources",
        ...Object.entries(body.drive ?? {}).filter(([, v]) => v === "added").map(([k]) => SPACES.find((x) => x.key === k)?.label)].filter(Boolean);
      const failed = Object.entries(body.drive ?? {}).filter(([, v]) => v !== "added").map(([k]) => SPACES.find((x) => x.key === k)?.label);
      toast(
        failed.length
          ? `Uploaded, but couldn't add it to ${failed.join(" and ")}. Ask an admin to check the Drive connection.`
          : done.length ? `Certificate uploaded and added to ${done.join(", ")}` : "Certificate uploaded",
        failed.length ? "info" : "success",
      );
      if (router.canGoBack()) router.back();
      else router.replace("/(tabs)/certificates");
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
      <Stack.Screen options={{ title: mode === "resource" ? "Share a resource" : "Upload certificate" }} />
      <View style={styles.modeRow}>
        <Chip label="Certificate" selected={mode === "certificate"} onPress={() => setMode("certificate")} testID="upload-mode-certificate" />
        <Chip label="Resource to share (no expiry)" selected={mode === "resource"} onPress={() => setMode("resource")} testID="upload-mode-resource" />
      </View>
      {file ? (
        <View style={styles.fileCard} testID="upload-selected-file">
          <IconBox name={file.mimeType?.includes("pdf") ? "document-text" : "image"} size={44} />
          <Text style={styles.fileName} numberOfLines={2}>{file.name}</Text>
          <Pressable testID="upload-remove-file" hitSlop={10} onPress={() => setFile(null)} style={styles.iconBtn}>
            <Ionicons name="close-circle" size={22} color={colors.muted} />
          </Pressable>
        </View>
      ) : (
        <View style={{ marginBottom: 20, gap: 12 }}>
        <Pressable testID="upload-take-photo" onPress={takePhoto} style={({ pressed }) => [styles.camera, pressed && { opacity: 0.85 }]}>
          <Ionicons name="camera" size={26} color={colors.onBrandPrimary} />
          <View style={{ flex: 1 }}>
            <Text style={styles.cameraText}>Take a photo</Text>
            <Text style={styles.cameraSub}>We&apos;ll fill in the details for you</Text>
          </View>
          <Ionicons name="sparkles" size={18} color={colors.onBrandPrimary} />
        </Pressable>
        <View style={[styles.pickRow, { marginBottom: 0 }]}>
          <Pressable testID="upload-pick-document" onPress={pickDoc} style={({ pressed }) => [styles.pick, pressed && { opacity: 0.7 }]}>
            <Ionicons name="document-attach-outline" size={28} color={colors.brandPrimary} />
            <Text style={styles.pickText}>Choose file</Text>
            <Text style={styles.pickSub}>PDF or image</Text>
          </Pressable>
          <Pressable testID="upload-pick-photo" onPress={pickPhoto} style={({ pressed }) => [styles.pick, pressed && { opacity: 0.7 }]}>
            <Ionicons name="images-outline" size={28} color={colors.brandPrimary} />
            <Text style={styles.pickText}>From photos</Text>
            <Text style={styles.pickSub}>{mode === "resource" ? "Photo or screenshot" : "Photo of certificate"}</Text>
          </Pressable>
        </View>
        </View>
      )}

      {file && mode === "certificate" && (
        <Button
          label={reading ? "Reading certificate…" : "Auto-fill details with AI"}
          icon="sparkles-outline"
          variant="secondary"
          loading={reading}
          onPress={() => autoFill()}
          style={{ marginBottom: 20 }}
          testID="upload-ai-autofill-button"
        />
      )}

      <Field label={mode === "resource" ? "Title" : "Certificate name"} value={title} onChangeText={setTitle} placeholder={mode === "resource" ? "e.g. Autism & sensory processing webinar" : "e.g. First Aid at Work"} testID="upload-title-input" />
      <Field label={mode === "resource" ? "Provider (optional)" : "Issued by (optional)"} value={issuer} onChangeText={setIssuer} placeholder={mode === "resource" ? "e.g. OT Australia" : "e.g. St John Ambulance"} testID="upload-issuer-input" />
      {mode === "certificate" && (
        <>
      <Field label={`Issue date (${DMY_HINT})`} value={issueDate} onChangeText={setIssueDate} placeholder="15-01-2026" autoCapitalize="none" testID="upload-issue-date-input" />
      <Field label={`Expiry date (${DMY_HINT})`} value={expiry} onChangeText={setExpiry} placeholder="15-01-2027" autoCapitalize="none" testID="upload-expiry-date-input" />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }} style={{ marginTop: -4, marginBottom: 20 }}>
        {[1, 2, 3, 5].map((n) => (
          <Chip key={n} label={`+${n} year${n > 1 ? "s" : ""}`} selected={expiry === addYears(n)} onPress={() => setExpiry(addYears(n))} testID={`upload-expiry-quick-${n}`} />
        ))}
      </ScrollView>
      <Text style={styles.hint}>We&apos;ll remind you in the app and by email 30 days before it expires.</Text>
        </>
      )}
      <View style={styles.cpdBox} testID="upload-cpd-box">
        <View style={styles.cpdRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.cpdTitle}>Count towards my CPD hours</Text>
            <Text style={styles.pickSub}>{mode === "resource" ? "Adds it to My CPD with the file as evidence" : "Adds this training to My CPD with the certificate as evidence"}</Text>
          </View>
          <Switch testID="upload-cpd-switch" value={countCpd} onValueChange={setCountCpd} trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }} />
        </View>
        {countCpd && (
          <Field label="Hours completed" value={cpdHours} onChangeText={setCpdHours} keyboardType="decimal-pad" placeholder="e.g. 3" testID="upload-cpd-hours-input" style={{ marginBottom: 0 }} />
        )}
      </View>
      <View style={styles.cpdBox} testID="upload-share-box">
        <Text style={styles.cpdTitle}>Also share it with the team</Text>
        <View style={styles.cpdRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.shareTitle}>Add to CPD Resources</Text>
            <Text style={styles.pickSub}>Everyone can open it from the CPD Resource Library</Text>
          </View>
          <Switch testID="upload-share-cpd-switch" value={shareCpd} onValueChange={setShareCpd} trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }} />
        </View>
        {shareCpd && (
          <View style={styles.typeRow}>
            {CPD_TYPES.map((t) => (
              <Chip key={t} label={t} selected={shareType === t} onPress={() => setShareType(t)} testID={`upload-share-type-${t}`} />
            ))}
          </View>
        )}
        {SPACES.filter((s) => drive.data?.spaces?.[s.key]?.folder_id).map((s) => (
          <View key={s.key} style={styles.cpdRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.shareTitle}>Add to {s.label}</Text>
              <Text style={styles.pickSub}>Saves a copy in the Company Drive folder</Text>
            </View>
            <Switch testID={`upload-share-${s.key}-switch`} value={spaces.includes(s.key)} onValueChange={() => toggleSpace(s.key)} trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }} />
          </View>
        ))}
      </View>
      {error && <Text style={styles.error} testID="upload-error">{error}</Text>}
      <Button label={mode === "resource" ? "Share resource" : "Upload certificate"} icon="cloud-upload-outline" loading={saving} onPress={submit} testID="upload-submit-button" />
      <Modal visible={!!camSheet} transparent animationType="fade" onRequestClose={() => setCamSheet(null)}>
        <Pressable style={styles.scrim} onPress={() => setCamSheet(null)} />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID="camera-permission-sheet">
          <IconBox name="camera" size={52} />
          <Text style={styles.sheetTitle}>{camSheet === "settings" ? "Camera access is off" : "Snap your certificate"}</Text>
          <Text style={styles.sheetMsg}>
            {camSheet === "settings"
              ? "Turn on camera access for StaffHub in Settings to photograph certificates. You can still choose a file instead."
              : "Allow camera access to photograph your certificate. Claude reads it and fills in the name and dates for you."}
          </Text>
          {camSheet === "settings" ? (
            <Button label="Open Settings" icon="settings-outline" onPress={() => { setCamSheet(null); Linking.openSettings(); }} testID="camera-open-settings" />
          ) : (
            <Button label="Continue" onPress={requestCamera} testID="camera-permission-continue" />
          )}
          <Button label="Not now" variant="ghost" onPress={() => setCamSheet(null)} testID="camera-permission-cancel" />
        </View>
      </Modal>
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  pickRow: { flexDirection: "row", gap: 12, marginBottom: 20 },
  camera: { flexDirection: "row", alignItems: "center", gap: 14, borderRadius: 16, padding: 18, backgroundColor: c.brandPrimary, minHeight: 72 },
  cameraText: { fontSize: 17, fontWeight: "700", color: c.onBrandPrimary },
  cameraSub: { fontSize: 13, color: c.onBrandPrimary, opacity: 0.85, marginTop: 2 },
  scrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.35)" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, gap: 12, alignItems: "stretch" },
  sheetTitle: { fontSize: 19, fontWeight: "700", color: c.onSurface },
  sheetMsg: { fontSize: 15, color: c.onSurfaceSecondary, lineHeight: 21 },
  pick: { flex: 1, borderWidth: 1.5, borderStyle: "dashed", borderColor: c.borderStrong, borderRadius: 16, padding: 20, alignItems: "center", gap: 4, backgroundColor: c.brandTertiary },
  pickText: { fontSize: 15, fontWeight: "600", color: c.onSurface, marginTop: 4 },
  pickSub: { fontSize: 12, color: c.muted },
  fileCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, borderRadius: 16, backgroundColor: c.brandTertiary, marginBottom: 20 },
  fileName: { flex: 1, fontSize: 15, fontWeight: "600", color: c.onSurface },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  hint: { fontSize: 13, color: c.muted, marginBottom: 16, lineHeight: 18 },
  cpdBox: { backgroundColor: c.brandTertiary, borderRadius: 14, padding: 12, gap: 10, marginBottom: 16 },
  cpdRow: { flexDirection: "row", alignItems: "center", gap: 12, minHeight: 44 },
  cpdTitle: { fontSize: 15, fontWeight: "600", color: c.onSurface },
  shareTitle: { fontSize: 14, fontWeight: "600", color: c.onSurface },
  modeRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 16 },
  typeRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  error: { fontSize: 14, color: c.errorText, marginBottom: 12 },
}));
