// Shift handover photos: assigned Support Workers and Coordinators attach photos so the next worker sees what happened.
import { useState } from "react";
import { Linking, Modal, Platform, Pressable, ScrollView, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders, getApiToken } from "@/src/api";
import { Text, TextInput } from "@/src/components/text";
import { Sheet } from "@/src/components/participant-sheets";
import { useToast } from "@/src/components/toast";
import { Button, Ionicons, formatDate } from "@/src/components/ui";
import { uploadForm } from "@/src/utils/upload";
import { makeStyles, useTheme } from "@/src/theme";

type Photo = { photo_id: string; caption: string; by_name: string; by_id: string; at: string };

const photoUrl = (id: string) => `${API_URL}/caseload/handover/photos/${id}?token=${encodeURIComponent(getApiToken() ?? "")}`;

export function HandoverPhotos({ participant, handoverId, photos, myId, canManage, onChange }: {
  participant: string; handoverId: string; photos: Photo[]; myId?: string; canManage?: boolean; onChange: () => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [viewing, setViewing] = useState<Photo | null>(null);
  const [camAsk, setCamAsk] = useState<null | "ask" | "settings">(null);
  const [pending, setPending] = useState<ImagePicker.ImagePickerAsset | null>(null);
  const [caption, setCaption] = useState("");
  const [editCap, setEditCap] = useState<string | null>(null);

  const pick = (a: ImagePicker.ImagePickerAsset) => { setCaption(""); setPending(a); };
  const upload = async (a: ImagePicker.ImagePickerAsset) => {
    setBusy(true);
    try {
      const res = await uploadForm(`${API_URL}/caseload/handover/photos`, {
        headers: authHeaders(),
        fields: { participant, submission_id: handoverId, caption: caption.trim() },
        files: { file: { uri: a.uri, name: a.fileName ?? "handover.jpg", mimeType: a.mimeType ?? "image/jpeg" } },
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Couldn't add the photo");
      toast("Photo added to the handover", "success");
      setPending(null);
      onChange();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const saveCaption = async () => {
    if (!viewing || editCap === null) return;
    try {
      const r = await api<Photo>(`/caseload/handover/photos/${viewing.photo_id}`, { method: "PATCH", body: { caption: editCap } });
      setViewing({ ...viewing, caption: r.caption });
      setEditCap(null);
      toast("Caption saved", "success");
      onChange();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const fromLibrary = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7 });
    if (!r.canceled && r.assets?.[0]) pick(r.assets[0]);
  };
  const launchCamera = async () => {
    setCamAsk(null);
    const r = await ImagePicker.launchCameraAsync({ mediaTypes: ["images"], quality: 0.7 });
    if (!r.canceled && r.assets?.[0]) pick(r.assets[0]);
  };
  const takePhoto = async () => {
    if (Platform.OS === "web") return launchCamera();
    const perm = await ImagePicker.getCameraPermissionsAsync();
    if (perm.granted) return launchCamera();
    setCamAsk(perm.status === "undetermined" || perm.canAskAgain ? "ask" : "settings");
  };
  const requestCamera = async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (perm.granted) return launchCamera();
    setCamAsk(perm.canAskAgain ? null : "settings");
    if (perm.canAskAgain) toast("Camera access is needed to take a photo. You can still choose one from your library.", "info");
  };
  const remove = async (p: Photo) => {
    try {
      await api(`/caseload/handover/photos/${p.photo_id}`, { method: "DELETE" });
      setViewing(null);
      toast("Photo removed", "success");
      onChange();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <View style={{ gap: 8 }} testID={`handover-photos-${participant}`}>
      {!!photos.length && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
          {photos.map((p) => (
            <Pressable key={p.photo_id} onPress={() => { setEditCap(null); setViewing(p); }} accessibilityLabel={`Handover photo from ${p.by_name}`}
              testID={`handover-photo-${p.photo_id}`} style={{ width: 88 }}>
              <Image source={{ uri: photoUrl(p.photo_id) }} style={styles.thumb} contentFit="cover" />
              {!!p.caption && <Text style={styles.thumbCap} numberOfLines={2}>{p.caption}</Text>}
            </Pressable>
          ))}
        </ScrollView>
      )}
      {photos.length < 10 && (
        <View style={styles.row}>
          <Button label="Take photo" icon="camera-outline" variant="secondary" loading={busy} disabled={busy} onPress={takePhoto}
            style={{ flex: 1 }} testID={`handover-photo-camera-${participant}`} />
          <Button label="Add from library" icon="images-outline" variant="secondary" disabled={busy} onPress={fromLibrary}
            style={{ flex: 1 }} testID={`handover-photo-library-${participant}`} />
        </View>
      )}

      <Modal visible={!!camAsk} transparent animationType="fade" onRequestClose={() => setCamAsk(null)}>
        <Pressable style={styles.scrim} onPress={() => setCamAsk(null)} />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID="handover-camera-permission">
          <Text style={styles.title}>Use your camera</Text>
          <Text style={styles.meta}>
            {camAsk === "settings"
              ? "Camera access is turned off for No Limitts. Turn it on in Settings to photograph handovers, or add a photo from your library."
              : "Snap what happened on shift so the next Support Worker sees it in the handover."}
          </Text>
          {camAsk === "settings"
            ? <Button label="Open Settings" icon="settings-outline" onPress={() => { setCamAsk(null); Linking.openSettings(); }} testID="handover-camera-settings" />
            : <Button label="Allow camera" icon="camera-outline" onPress={requestCamera} testID="handover-camera-allow" />}
          <Button label="Not now" variant="ghost" onPress={() => setCamAsk(null)} />
        </View>
      </Modal>

      <Sheet visible={!!pending} onClose={() => !busy && setPending(null)} title="Add to handover"
        sub="Add a short caption so the next Support Worker knows what this shows." testID="handover-caption-sheet">
        {pending && <Image source={{ uri: pending.uri }} style={styles.preview} contentFit="cover" />}
        <TextInput value={caption} onChangeText={setCaption} placeholder="e.g. New bruise on left arm, reported to coordinator"
          placeholderTextColor={colors.muted} maxLength={200} style={styles.input} testID="handover-caption-input" />
        <Button label="Add photo" icon="cloud-upload-outline" loading={busy} disabled={busy} onPress={() => pending && upload(pending)}
          testID="handover-caption-save" />
        <Button label="Cancel" variant="ghost" disabled={busy} onPress={() => setPending(null)} />
      </Sheet>

      <Modal visible={!!viewing} animationType="fade" onRequestClose={() => setViewing(null)}>
        <KeyboardAvoidingView behavior="padding" style={{ flex: 1 }}>
        <View style={[styles.viewer, { paddingTop: insets.top + 8, paddingBottom: insets.bottom + 16 }]} testID="handover-photo-viewer">
          <View style={styles.row}>
            <Text style={[styles.viewerText, { flex: 1 }]}>{viewing ? `${viewing.by_name} · ${formatDate(viewing.at)}` : ""}</Text>
            <Pressable onPress={() => setViewing(null)} style={styles.close} accessibilityLabel="Close photo" testID="handover-photo-close">
              <Ionicons name="close" size={26} color="#FFFFFF" />
            </Pressable>
          </View>
          {viewing && <Image source={{ uri: photoUrl(viewing.photo_id) }} style={{ flex: 1 }} contentFit="contain" />}
          {viewing && editCap === null && !!viewing.caption && (
            <Text style={styles.viewerCap} testID="handover-photo-caption">{viewing.caption}</Text>
          )}
          {viewing && (viewing.by_id === myId || canManage) && (editCap === null ? (
            <View style={styles.row}>
              <Button label={viewing.caption ? "Edit caption" : "Add caption"} icon="create-outline" variant="secondary" style={{ flex: 1 }}
                onPress={() => setEditCap(viewing.caption)} testID="handover-photo-edit-caption" />
              <Button label="Remove" icon="trash-outline" variant="danger" style={{ flex: 1 }} onPress={() => remove(viewing)} testID="handover-photo-remove" />
            </View>
          ) : (
            <View style={{ gap: 8 }}>
              <TextInput value={editCap} onChangeText={setEditCap} placeholder="Caption" placeholderTextColor={colors.muted} maxLength={200}
                style={styles.input} autoFocus testID="handover-photo-caption-input" />
              <View style={styles.row}>
                <Button label="Save" icon="checkmark" style={{ flex: 1 }} onPress={saveCaption} testID="handover-photo-caption-save" />
                <Button label="Cancel" variant="secondary" style={{ flex: 1 }} onPress={() => setEditCap(null)} />
              </View>
            </View>
          ))}
        </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  thumb: { width: 88, height: 88, borderRadius: 10, backgroundColor: c.surfaceSecondary },
  scrim: { flex: 1, backgroundColor: c.scrim },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 20, gap: 12 },
  title: { fontSize: 18, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 14, color: c.muted, lineHeight: 20 },
  viewer: { flex: 1, backgroundColor: "#000000", paddingHorizontal: 16, gap: 12 },
  viewerText: { fontSize: 14, color: "#FFFFFF" },
  close: { width: 48, height: 48, alignItems: "center", justifyContent: "center" },
  thumbCap: { fontSize: 11, color: c.muted, marginTop: 2 },
  viewerCap: { fontSize: 15, color: "#FFFFFF", lineHeight: 21 },
  preview: { width: "100%", height: 180, borderRadius: 12, backgroundColor: c.surfaceSecondary },
  input: { minHeight: 48, borderRadius: 12, paddingHorizontal: 14, fontSize: 15, color: c.onSurface, backgroundColor: c.surfaceSecondary },
}));
