// Shift handover photos: assigned Support Workers and Coordinators attach photos so the next worker sees what happened.
import { useState } from "react";
import { Linking, Modal, Platform, Pressable, ScrollView, View } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders, getApiToken } from "@/src/api";
import { Text } from "@/src/components/text";
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

  const upload = async (a: ImagePicker.ImagePickerAsset) => {
    setBusy(true);
    try {
      const res = await uploadForm(`${API_URL}/caseload/handover/photos`, {
        headers: authHeaders(),
        fields: { participant, submission_id: handoverId },
        files: { file: { uri: a.uri, name: a.fileName ?? "handover.jpg", mimeType: a.mimeType ?? "image/jpeg" } },
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Couldn't add the photo");
      toast("Photo added to the handover", "success");
      onChange();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const fromLibrary = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7 });
    if (!r.canceled && r.assets?.[0]) upload(r.assets[0]);
  };
  const launchCamera = async () => {
    setCamAsk(null);
    const r = await ImagePicker.launchCameraAsync({ mediaTypes: ["images"], quality: 0.7 });
    if (!r.canceled && r.assets?.[0]) upload(r.assets[0]);
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
            <Pressable key={p.photo_id} onPress={() => setViewing(p)} accessibilityLabel={`Handover photo from ${p.by_name}`}
              testID={`handover-photo-${p.photo_id}`}>
              <Image source={{ uri: photoUrl(p.photo_id) }} style={styles.thumb} contentFit="cover" />
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

      <Modal visible={!!viewing} animationType="fade" onRequestClose={() => setViewing(null)}>
        <View style={[styles.viewer, { paddingTop: insets.top + 8, paddingBottom: insets.bottom + 16 }]} testID="handover-photo-viewer">
          <View style={styles.row}>
            <Text style={[styles.viewerText, { flex: 1 }]}>{viewing ? `${viewing.by_name} · ${formatDate(viewing.at)}` : ""}</Text>
            <Pressable onPress={() => setViewing(null)} style={styles.close} accessibilityLabel="Close photo" testID="handover-photo-close">
              <Ionicons name="close" size={26} color="#FFFFFF" />
            </Pressable>
          </View>
          {viewing && <Image source={{ uri: photoUrl(viewing.photo_id) }} style={{ flex: 1 }} contentFit="contain" />}
          {viewing && (viewing.by_id === myId || canManage) && (
            <Button label="Remove photo" icon="trash-outline" variant="danger" onPress={() => remove(viewing)} testID="handover-photo-remove" />
          )}
        </View>
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
}));
