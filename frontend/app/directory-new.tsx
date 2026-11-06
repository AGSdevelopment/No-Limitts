import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/src/components/text";
import * as DocumentPicker from "expo-document-picker";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, Chip, EmptyState, Field, Ionicons } from "@/src/components/ui";
import { CATEGORIES, DirSpace } from "@/src/directory";
import { makeStyles, useTheme } from "@/src/theme";
import { LocalFile, uploadForm } from "@/src/utils/upload";

type Target = DirSpace | "favourite";
const TARGETS: { key: Target; label: string }[] = [
  { key: "therapist", label: "Support Worker" },
  { key: "participant", label: "Participant" },
  { key: "favourite", label: "No Limitts Favourite" },
];
const EMPTY = { name: "", services: "", contact: "", phone: "", email: "", address: "", link: "", note: "" };

export default function DirectoryNew() {
  const params = useLocalSearchParams<{ space?: DirSpace; category?: string; edit?: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const existing = useQuery<any>({ queryKey: ["directory-entry", params.edit], queryFn: () => api(`/directory/${params.edit}`), enabled: !!params.edit });
  const [target, setTarget] = useState<Target>(params.space ?? "therapist");
  const [category, setCategory] = useState(params.category ?? "");
  const [f, setF] = useState(EMPTY);
  const [files, setFiles] = useState<LocalFile[]>([]);
  const [saving, setSaving] = useState(false);
  const isReferral = category === "Trusted Referral Partner Organisations";
  const set = (k: keyof typeof EMPTY) => (v: string) => setF({ ...f, [k]: v });

  useEffect(() => {
    const e = existing.data;
    if (e) {
      setTarget(e.space);
      setCategory(e.category);
      setF({ name: e.name, services: e.services ?? "", contact: e.contact, phone: e.phone, email: e.email, address: e.address, link: e.link, note: e.note });
    }
  }, [existing.data]);

  const isAdmin = user?.role === "admin";
  const suggesting = !isAdmin && !params.edit;
  const SUGGESTABLE = ["Suppliers", "Activities"];
  const suggestCategory = params.category && SUGGESTABLE.includes(params.category) ? params.category : "Suppliers";
  useEffect(() => {
    if (suggesting) {
      setTarget(params.space ?? "therapist");
      setCategory(suggestCategory);
    }
  }, [suggesting, suggestCategory, params.space]);

  if (!isAdmin && !suggesting) return <EmptyState icon="lock-closed-outline" title="Admins only" subtitle="Ask an admin to add this for you." />;

  const pickTarget = (t: Target) => {
    if (t === "favourite") {
      router.replace("/places?add=1");
      return;
    }
    setTarget(t);
    if (!CATEGORIES[t].includes(category)) setCategory("");
  };

  const pickFiles = async () => {
    const r = await DocumentPicker.getDocumentAsync({ type: "*/*", multiple: true, copyToCacheDirectory: true });
    if (r.canceled) return;
    setFiles([...files, ...r.assets.map((a) => ({ uri: a.uri, name: a.name, mimeType: a.mimeType ?? undefined }))].slice(0, 10));
  };

  const removeExistingFile = async (fileId: string) => {
    try {
      await api(`/directory/${params.edit}/files/${fileId}`, { method: "DELETE" });
      existing.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const save = async () => {
    const space = target as DirSpace;
    if (!category) return toast("Choose a category", "error");
    if (!f.name.trim()) return toast("Add a name", "error");
    setSaving(true);
    try {
      const body = { ...f, space, category };
      const entry = params.edit
        ? await api(`/directory/${params.edit}`, { method: "PUT", body })
        : await api("/directory", { method: "POST", body });
      let failed = 0;
      for (const file of files) {
        const res = await uploadForm(`${API_URL}/directory/${entry.entry_id}/files`, { headers: authHeaders(), files: { file } });
        if (!res.ok) failed += 1;
      }
      qc.invalidateQueries({ queryKey: ["directory"] });
      qc.invalidateQueries({ queryKey: ["directory-highlights"] });
      qc.invalidateQueries({ queryKey: ["directory-entry", params.edit] });
      toast(failed ? `Saved, but ${failed} file${failed > 1 ? "s" : ""} couldn't upload` : suggesting ? `Thanks! ${f.name.trim()} was sent to an admin for approval` : `${f.name.trim()} saved to ${category}`, failed ? "info" : "success");
      router.back();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <KeyboardAwareScrollView style={styles.root} contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 24 }} keyboardShouldPersistTaps="handled" bottomOffset={24} testID="directory-new-screen">
      <Stack.Screen options={{ title: params.edit ? "Edit entry" : suggesting ? `Suggest ${suggestCategory === "Suppliers" ? "a supplier" : "an activity"}` : "Add to Company Drive" }} />
      {suggesting && (
        <Text style={[styles.label, { marginBottom: 16 }]} testID="directory-suggest-intro">
          Suggest {suggestCategory === "Suppliers" ? "a supplier" : "an activity"}. An admin will check it before it goes live for the team.
        </Text>
      )}
      {!params.edit && isAdmin && (
        <>
          <Text style={styles.label}>Add to</Text>
          <View style={styles.chips}>
            {TARGETS.map((t) => (
              <Chip key={t.key} label={t.label} selected={target === t.key} onPress={() => pickTarget(t.key)} testID={`directory-target-${t.key}`} />
            ))}
          </View>
        </>
      )}
      {target !== "favourite" && (
        <>
          {isAdmin && <Text style={styles.label}>Category</Text>}
          {isAdmin && (
          <View style={styles.chips}>
            {CATEGORIES[target].map((c) => (
              <Chip key={c} label={c} selected={category === c} onPress={() => setCategory(c)} testID={`directory-category-${c}`} />
            ))}
          </View>
          )}
          <Field label={isReferral ? "Company name" : "Name"} value={f.name} onChangeText={set("name")} placeholder={category === "Templates" ? "e.g. Session notes template" : isReferral ? "e.g. Perth Speech Pathology" : "e.g. Sensory Tools Australia"} testID="directory-name-input" />
          {isReferral && <Field label="Services offered" value={f.services} onChangeText={set("services")} placeholder="e.g. Speech therapy, feeding assessments" multiline testID="directory-services-input" />}
          {!isReferral && <Field label="Contact person (optional)" value={f.contact} onChangeText={set("contact")} placeholder="e.g. Sam Lee" testID="directory-contact-input" />}
          <Field label={isReferral ? "Phone number" : "Phone (optional)"} value={f.phone} onChangeText={set("phone")} placeholder="e.g. 08 9123 4567" keyboardType="phone-pad" testID="directory-phone-input" />
          {isReferral && <Field label="Website" value={f.link} onChangeText={set("link")} placeholder="https://" keyboardType="url" autoCapitalize="none" testID="directory-link-input" />}
          <Field label={isReferral ? "Email" : "Email (optional)"} value={f.email} onChangeText={set("email")} placeholder="name@example.com" keyboardType="email-address" autoCapitalize="none" testID="directory-email-input" />
          <Field label={isReferral ? "Location / postcode" : "Address or area (optional)"} value={f.address} onChangeText={set("address")} placeholder={isReferral ? "e.g. Joondalup WA 6027" : "e.g. Osborne Park"} testID="directory-address-input" />
          {!isReferral && <Field label="Website or link (optional)" value={f.link} onChangeText={set("link")} placeholder="https://" keyboardType="url" autoCapitalize="none" testID="directory-link-input" />}
          <Field label="Notes (optional)" value={f.note} onChangeText={set("note")} placeholder="What it's for, prices, how to refer…" multiline testID="directory-note-input" />

          <Text style={styles.label}>Files (optional)</Text>
          {(existing.data?.files ?? []).map((x: any) => (
            <View key={x.file_id} style={styles.file}>
              <Ionicons name="document-attach-outline" size={18} color={colors.accent} />
              <Text style={styles.fileName} numberOfLines={1}>{x.name}</Text>
              <Pressable onPress={() => removeExistingFile(x.file_id)} style={styles.iconBtn} accessibilityLabel="Remove file" testID={`directory-existing-file-remove-${x.file_id}`}>
                <Ionicons name="close-circle" size={20} color={colors.muted} />
              </Pressable>
            </View>
          ))}
          {files.map((x, i) => (
            <View key={`${x.uri}${i}`} style={styles.file}>
              <Ionicons name="document-outline" size={18} color={colors.brandPrimary} />
              <Text style={styles.fileName} numberOfLines={1}>{x.name}</Text>
              <Pressable onPress={() => setFiles(files.filter((_, j) => j !== i))} style={styles.iconBtn} accessibilityLabel="Remove file" testID={`directory-file-remove-${i}`}>
                <Ionicons name="close-circle" size={20} color={colors.muted} />
              </Pressable>
            </View>
          ))}
          <Button label="Attach files" icon="attach" variant="secondary" onPress={pickFiles} style={{ marginBottom: 16 }} testID="directory-attach-button" />
          <Button label={params.edit ? "Save changes" : suggesting ? "Send for approval" : "Add"} icon="checkmark" loading={saving} onPress={save} testID="directory-save-button" />
        </>
      )}
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  label: { fontSize: 14, fontWeight: "600", color: c.onSurfaceSecondary, marginBottom: 8 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 16 },
  file: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 44, paddingLeft: 10, borderRadius: 10, backgroundColor: c.surfaceSecondary, marginBottom: 8 },
  fileName: { flex: 1, fontSize: 14, color: c.onSurface },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
}));
