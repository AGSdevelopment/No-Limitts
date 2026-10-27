import { useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Modal, Pressable, RefreshControl, ScrollView, Switch, Text, View } from "react-native";
import { Stack } from "expo-router";
import * as DocumentPicker from "expo-document-picker";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders, getApiToken, openLink } from "@/src/api";
import { uploadForm } from "@/src/utils/upload";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, Chip, ConfirmSheet, EmptyState, ErrorState, Field, IconBox, IconName, Ionicons, Loading, dmyDate, dmyToIso, formatDate, isoToDmy } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Tab = "log" | "resources" | "team";
type Picked = { uri: string; name: string; mimeType?: string };
const CATEGORIES = ["Course", "Webinar", "Case Study", "Conference", "Reading", "Supervision", "Other"];
const RES_SECTIONS = ["Courses", "Webinars", "Case Studies", "Resource Links"];
const SECTION_ICON: Record<string, IconName> = { Courses: "school-outline", Webinars: "videocam-outline", "Case Studies": "briefcase-outline", "Resource Links": "link-outline" };

export default function Cpd() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("log");
  const [adding, setAdding] = useState(false);
  const [editLog, setEditLog] = useState<any>(null);
  const [del, setDel] = useState<{ kind: "log" | "res"; id: string } | null>(null);
  const logs = useQuery<any>({ queryKey: ["cpd", tab === "team" ? "all" : "mine"], queryFn: () => api(`/cpd?scope=${tab === "team" ? "all" : "mine"}`), enabled: tab !== "resources" });
  const res = useQuery<any[]>({ queryKey: ["cpd-resources"], queryFn: () => api("/cpd/resources"), enabled: tab === "resources" });

  const remove = async () => {
    if (!del) return;
    try {
      await api(del.kind === "log" ? `/cpd/${del.id}` : `/cpd/resources/${del.id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: [del.kind === "log" ? "cpd" : "cpd-resources"] });
      toast("Deleted", "info");
    } catch (e: any) {
      toast(e.message, "error");
    }
    setDel(null);
  };

  const active = tab === "resources" ? res : logs;
  const addLabel = tab === "resources" ? "Add resource" : "Log CPD";

  return (
    <View style={styles.root} testID="cpd-screen">
      <Stack.Screen
        options={{
          headerRight:
            tab === "log" || (tab === "resources" && isAdmin)
              ? () => (
                  <Pressable testID="cpd-add-button" onPress={() => setAdding(true)} hitSlop={10} accessibilityLabel={addLabel}>
                    <Ionicons name="add-circle" size={30} color={colors.brandPrimary} style={{ marginRight: 8 }} />
                  </Pressable>
                )
              : undefined,
        }}
      />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow} contentContainerStyle={styles.chipContent}>
        <Chip label="My CPD" selected={tab === "log"} onPress={() => setTab("log")} testID="cpd-tab-log" />
        <Chip label="Resources" selected={tab === "resources"} onPress={() => setTab("resources")} testID="cpd-tab-resources" />
        {isAdmin && <Chip label="Team hours" selected={tab === "team"} onPress={() => setTab("team")} testID="cpd-tab-team" />}
      </ScrollView>
      {active.isLoading ? (
        <Loading />
      ) : active.isError ? (
        <ErrorState message="Couldn't load CPD." onRetry={() => active.refetch()} />
      ) : tab === "resources" ? (
        <ScrollView
          contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24 }}
          refreshControl={<RefreshControl refreshing={res.isRefetching} onRefresh={() => res.refetch()} tintColor={colors.brandPrimary} />}
          testID="cpd-resources-list"
        >
          {RES_SECTIONS.map((section) => {
            const items = (res.data ?? []).filter((r) => r.category === section);
            return (
              <View key={section} style={{ gap: 10, marginBottom: 12 }} testID={`cpd-section-${section}`}>
                <View style={styles.sectionHead}>
                  <Ionicons name={SECTION_ICON[section]} size={18} color={colors.brandPrimary} />
                  <Text style={styles.sectionTitle}>{section}</Text>
                  <Text style={styles.sub}>{items.length}</Text>
                </View>
                {items.length === 0 ? (
                  <Text style={styles.sectionEmpty}>Nothing here yet.</Text>
                ) : (
                  items.map((item) => {
                    const canDelete = isAdmin;
                    const fileUrl = `${API_URL}/cpd/resources/${item.resource_id}/file?token=${encodeURIComponent(getApiToken() ?? "")}`;
                    return (
                      <Pressable key={item.resource_id} testID={`cpd-resource-${item.resource_id}`} onPress={() => (item.url ? openLink(item.url) : item.has_file ? openLink(fileUrl) : undefined)} style={styles.card}>
                        <IconBox name={item.has_file ? "document-text-outline" : SECTION_ICON[section]} size={40} />
                        <View style={{ flex: 1, gap: 2 }}>
                          <Text style={styles.title}>{item.title}</Text>
                          {!!item.description && <Text style={styles.desc} numberOfLines={3}>{item.description}</Text>}
                          <Text style={styles.sub}>Shared by {item.created_by}</Text>
                          {(!!item.url || item.has_file) && <Text style={styles.link} numberOfLines={1}>{item.url ? "Open link" : "View document"}</Text>}
                        </View>
                        {canDelete && (
                          <Pressable testID={`cpd-resource-delete-${item.resource_id}`} onPress={() => setDel({ kind: "res", id: item.resource_id })} hitSlop={6} style={styles.iconBtn}>
                            <Ionicons name="trash-outline" size={20} color={colors.muted} />
                          </Pressable>
                        )}
                      </Pressable>
                    );
                  })
                )}
              </View>
            );
          })}
          <Text style={styles.sectionEmpty}>Tip: share your own learning from My CPD to add it here.</Text>
        </ScrollView>
      ) : (
        <FlatList
          data={tab === "team" ? logs.data?.team_totals : logs.data?.logs}
          keyExtractor={(l) => l.log_id ?? l.user_id}
          contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={logs.isRefetching} onRefresh={() => logs.refetch()} tintColor={colors.brandPrimary} />}
          ListHeaderComponent={
            tab === "log" ? (
              <View style={styles.total} testID="cpd-year-total">
                <Text style={styles.totalNum}>{logs.data?.year_hours ?? 0}</Text>
                <Text style={styles.totalLabel}>CPD hours logged in {logs.data?.year}</Text>
                <Pressable
                  testID="cpd-report-button"
                  onPress={() => openLink(`${API_URL}/cpd/report?year=${logs.data?.year}&token=${encodeURIComponent(getApiToken() ?? "")}`)}
                  style={({ pressed }) => [styles.reportBtn, pressed && { opacity: 0.85 }]}
                  accessibilityLabel="Download CPD report"
                >
                  <Ionicons name="download-outline" size={18} color={colors.brandPrimary} />
                  <Text style={styles.reportText}>Download {logs.data?.year} report (PDF)</Text>
                </Pressable>
              </View>
            ) : (
              <Text style={styles.teamHead}>Hours logged in {logs.data?.year}</Text>
            )
          }
          ListEmptyComponent={
            <EmptyState
              icon="time-outline"
              title={tab === "team" ? "No CPD logged this year" : "No CPD logged yet"}
              subtitle={tab === "log" ? "Tap + to record a course, webinar or other learning." : undefined}
              testID="cpd-empty"
            />
          }
          renderItem={({ item }) =>
            tab === "team" ? (
              <View style={styles.card} testID={`cpd-team-${item.user_id}`}>
                <Text style={[styles.title, { flex: 1 }]}>{item.user_name}</Text>
                <Text style={styles.hours}>{Math.round(item.hours * 100) / 100} h</Text>
              </View>
            ) : (
              <Pressable style={styles.card} testID={`cpd-log-${item.log_id}`} onPress={() => setEditLog(item)} accessibilityLabel={`Edit ${item.title}`}>
                <View style={styles.hoursBox}>
                  <Text style={styles.hoursBig}>{item.hours}</Text>
                  <Text style={styles.hoursUnit}>hrs</Text>
                </View>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={styles.title}>{item.title}</Text>
                  <Text style={styles.sub}>{[item.category, item.provider, formatDate(item.date)].filter(Boolean).join(" · ")}</Text>
                  {!!item.notes && <Text style={styles.desc} numberOfLines={2}>{item.notes}</Text>}
                  {!!item.storage_path && (
                    <Pressable testID={`cpd-log-file-${item.log_id}`} onPress={() => openLink(`${API_URL}/cpd/${item.log_id}/file?token=${encodeURIComponent(getApiToken() ?? "")}`)} hitSlop={6} style={styles.fileLink}>
                      <Ionicons name="attach" size={16} color={colors.brandPrimary} />
                      <Text style={styles.link}>View certificate</Text>
                    </Pressable>
                  )}
                </View>
                <Pressable testID={`cpd-log-edit-${item.log_id}`} onPress={() => setEditLog(item)} hitSlop={6} style={styles.iconBtn} accessibilityLabel="Edit">
                  <Ionicons name="create-outline" size={20} color={colors.brandPrimary} />
                </Pressable>
                <Pressable testID={`cpd-log-delete-${item.log_id}`} onPress={() => setDel({ kind: "log", id: item.log_id })} hitSlop={6} style={styles.iconBtn}>
                  <Ionicons name="trash-outline" size={20} color={colors.muted} />
                </Pressable>
              </Pressable>
            )
          }
        />
      )}
      <AddSheet kind={tab === "resources" ? "resource" : "log"} visible={adding || !!editLog} editing={editLog} onClose={() => { setAdding(false); setEditLog(null); }} />
      <ConfirmSheet visible={!!del} title="Delete this?" message="This can't be undone." confirmLabel="Delete" onConfirm={remove} onClose={() => setDel(null)} />
    </View>
  );
}

function AddSheet({ kind, visible, onClose, editing }: { kind: "log" | "resource"; visible: boolean; onClose: () => void; editing?: any }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [provider, setProvider] = useState("");
  const [date, setDate] = useState(dmyDate(new Date()));
  const [hours, setHours] = useState("");
  const [category, setCategory] = useState("");
  const [notes, setNotes] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<Picked | null>(null);
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [share, setShare] = useState(false);
  const [shareSection, setShareSection] = useState<string>("Resource Links");
  const close = () => onClose();

  useEffect(() => {
    if (visible && !editing) reset();
    if (visible && editing) {
      setTitle(editing.title ?? "");
      setProvider(editing.provider ?? "");
      setDate(isoToDmy(editing.date));
      setHours(String(editing.hours ?? ""));
      setCategory(editing.category ?? "");
      setNotes(editing.notes ?? "");
      setFile(null);
      setShare(false);
      setError(null);
    }
  }, [visible, editing]);

  const readFile = async (f: Picked) => {
    setReading(true);
    setError(null);
    try {
      const res = await uploadForm(`${API_URL}/cpd/extract`, { headers: authHeaders(), files: { file: f } });
      const b = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof b.detail === "string" ? b.detail : "Couldn't read the certificate");
      // when editing, only fill gaps so the user's own changes aren't overwritten
      const fill = (cur: string, v: string, set: (x: string) => void) => v && (!editing || !cur) && set(v);
      fill(title, b.title, setTitle);
      fill(provider, b.provider, setProvider);
      if (b.date && !editing) setDate(isoToDmy(b.date));
      fill(hours, b.hours ? String(b.hours) : "", setHours);
      if (b.category && (!editing || !category)) {
        setCategory(b.category);
        setShareSection(b.category === "Course" ? "Courses" : b.category === "Webinar" ? "Webinars" : b.category === "Case Study" ? "Case Studies" : "Resource Links");
      }
      toast(b.hours ? "Details filled in. Check and edit anything below." : "Hours couldn't be read. Please add them.", b.hours ? "success" : "info");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setReading(false);
    }
  };
  const pickFile = async () => {
    const r = await DocumentPicker.getDocumentAsync({ type: ["application/pdf", "image/*"], copyToCacheDirectory: true });
    if (!r.canceled && r.assets?.[0]) {
      const a = r.assets[0];
      const f = { uri: a.uri, name: a.name, mimeType: a.mimeType ?? undefined };
      setFile(f);
      readFile(f);
    }
  };

  const reset = () => {
    setTitle(""); setProvider(""); setHours(""); setCategory(""); setNotes(""); setUrl(""); setError(null); setFile(null);
    setShare(false); setShareSection("Resource Links");
    setDate(dmyDate(new Date()));
  };
  const save = async () => {
    setError(null);
    if (!title.trim()) return setError(kind === "log" ? "Enter what you did." : "Enter a title.");
    if (kind === "log") {
      if (!dmyToIso(date)) return setError("Date must be DD-MM-YYYY.");
      const h = parseFloat(hours.replace(",", "."));
      if (!h || h <= 0) return setError("Enter the number of hours.");
    }
    setSaving(true);
    try {
      if (kind === "log") {
        const body = { title, provider, date: dmyToIso(date), hours: parseFloat(hours.replace(",", ".")), category, notes };
        const log = editing ? await api(`/cpd/${editing.log_id}`, { method: "PATCH", body }) : await api("/cpd", { method: "POST", body });
        if (file) {
          const up = await uploadForm(`${API_URL}/cpd/${log.log_id}/file`, { headers: authHeaders(), files: { file } });
          if (!up.ok) toast("Saved, but the certificate couldn't be attached", "error");
        }
        let shared = false;
        if (share) {
          shared = await api(`/cpd/${log.log_id}/share`, { method: "POST", body: { category: shareSection } })
            .then(() => true)
            .catch(() => false);
          qc.invalidateQueries({ queryKey: ["cpd-resources"] });
        }
        qc.invalidateQueries({ queryKey: ["cpd"] });
        if (share && !shared) toast(editing ? "Saved, but sharing to the library failed" : "CPD logged, but sharing to the library failed", "error");
        else toast(editing ? (shared ? "Changes saved and shared" : "Changes saved") : shared ? "CPD logged and shared" : "CPD logged");
      } else {
        await api("/cpd/resources", { method: "POST", body: { title, description: notes, url, category } });
        qc.invalidateQueries({ queryKey: ["cpd-resources"] });
        toast("Resource added");
      }
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={close}>
      <KeyboardAwareScrollView style={styles.sheet} contentContainerStyle={{ padding: 20, paddingBottom: insets.bottom + 24 }} keyboardShouldPersistTaps="handled" bottomOffset={24} testID="cpd-add-sheet">
        <View style={styles.sheetHead}>
          <Text style={styles.sheetTitle}>{kind === "log" ? (editing ? "Edit CPD" : "Log CPD") : "Add CPD resource"}</Text>
          <Pressable onPress={close} hitSlop={10} style={styles.iconBtn} testID="cpd-add-close">
            <Ionicons name="close" size={24} />
          </Pressable>
        </View>
        {kind === "log" && (
          file ? (
            <View style={styles.fileCard} testID="cpd-attached-file">
              <IconBox name={file.mimeType?.includes("pdf") ? "document-text" : "image"} size={40} />
              <View style={{ flex: 1 }}>
                <Text style={styles.title} numberOfLines={1}>{file.name}</Text>
                <Text style={styles.sub}>{reading ? "Claude is reading the certificate…" : "Certificate attached"}</Text>
              </View>
              {reading ? (
                <ActivityIndicator color={colors.brandPrimary} />
              ) : (
                <Pressable testID="cpd-remove-file" onPress={() => setFile(null)} hitSlop={8} style={styles.iconBtn}>
                  <Ionicons name="close-circle" size={22} color={colors.muted} />
                </Pressable>
              )}
            </View>
          ) : (
            <Pressable testID="cpd-attach-button" onPress={pickFile} style={({ pressed }) => [styles.attach, pressed && { opacity: 0.8 }]}>
              <Ionicons name="sparkles" size={22} color={colors.brandPrimary} />
              <View style={{ flex: 1 }}>
                <Text style={styles.title}>{editing?.storage_path ? "Replace certificate" : "Attach certificate"}</Text>
                <Text style={styles.sub}>PDF or photo. We&apos;ll fill in the details; you can edit anything after.</Text>
              </View>
              <Ionicons name="attach" size={22} color={colors.brandPrimary} />
            </Pressable>
          )
        )}
        <Field label={kind === "log" ? "What did you do?" : "Title"} value={title} onChangeText={setTitle} placeholder={kind === "log" ? "e.g. AAC in early intervention webinar" : "e.g. Speech Pathology Australia webinars"} testID="cpd-title-input" />
        <Text style={styles.label}>{kind === "log" ? "Type" : "Section"}</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }} style={{ marginBottom: 16 }}>
          {(kind === "log" ? CATEGORIES : RES_SECTIONS).map((c) => (
            <Chip key={c} label={c} selected={category === c} onPress={() => setCategory(category === c ? "" : c)} testID={`cpd-category-${c}`} />
          ))}
        </ScrollView>
        {kind === "log" ? (
          <>
            <Field label="Provider (optional)" value={provider} onChangeText={setProvider} placeholder="e.g. Speech Pathology Australia" testID="cpd-provider-input" />
            <Field label="Date (DD-MM-YYYY)" value={date} onChangeText={setDate} autoCapitalize="none" placeholder="e.g. 12-05-2026" testID="cpd-date-input" />
            <Field label="Hours taken to complete" value={hours} onChangeText={setHours} keyboardType="decimal-pad" placeholder="e.g. 1.5" testID="cpd-hours-input" />
            <Field label="Notes (optional)" value={notes} onChangeText={setNotes} multiline placeholder="What you learned" testID="cpd-notes-input" />
            {!editing?.shared_resource_id && (
            <View style={styles.shareBox}>
              <View style={styles.shareRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.title}>Share to CPD Resource Library</Text>
                  <Text style={styles.sub}>Let colleagues find this {file ? "and its document" : "learning"} too</Text>
                </View>
                <Switch testID="cpd-share-switch" value={share} onValueChange={setShare} trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }} />
              </View>
              {share && (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
                  {RES_SECTIONS.map((s) => (
                    <Chip key={s} label={s} selected={shareSection === s} onPress={() => setShareSection(s)} testID={`cpd-share-section-${s}`} />
                  ))}
                </ScrollView>
              )}
            </View>
            )}
          </>
        ) : (
          <>
            <Field label="Link (optional)" value={url} onChangeText={setUrl} autoCapitalize="none" keyboardType="url" placeholder="https://…" testID="cpd-url-input" />
            <Field label="Description (optional)" value={notes} onChangeText={setNotes} multiline testID="cpd-desc-input" />
          </>
        )}
        {error && <Text style={styles.error} testID="cpd-add-error">{error}</Text>}
        <Button label={kind === "log" ? (editing ? "Save changes" : "Save CPD") : "Add resource"} loading={saving} disabled={reading} onPress={save} testID="cpd-save-button" />
      </KeyboardAwareScrollView>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  chipRow: { flexGrow: 0, height: 56, backgroundColor: c.surface },
  chipContent: { paddingHorizontal: 16, gap: 8, alignItems: "center" },
  card: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 14, padding: 14, minHeight: 56 },
  title: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  desc: { fontSize: 14, color: c.onSurfaceSecondary, marginTop: 2 },
  link: { fontSize: 14, fontWeight: "600", color: c.brandPrimary, marginTop: 4 },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  total: { backgroundColor: c.brandPrimary, borderRadius: 16, padding: 20, marginBottom: 6, gap: 4 },
  totalNum: { fontSize: 40, fontWeight: "800", color: c.onBrandPrimary },
  totalLabel: { fontSize: 15, color: c.onBrandPrimary, opacity: 0.9 },
  reportBtn: { flexDirection: "row", alignItems: "center", gap: 8, alignSelf: "flex-start", backgroundColor: c.surface, borderRadius: 12, paddingHorizontal: 14, minHeight: 44, marginTop: 10 },
  reportText: { fontSize: 14, fontWeight: "700", color: c.brandPrimary },
  teamHead: { fontSize: 13, fontWeight: "600", color: c.muted, textTransform: "uppercase", marginLeft: 4, marginBottom: 4 },
  hours: { fontSize: 16, fontWeight: "700", color: c.brandPrimary },
  hoursBox: { width: 52, height: 52, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  hoursBig: { fontSize: 17, fontWeight: "800", color: c.brandPrimary },
  hoursUnit: { fontSize: 11, color: c.brandPrimary },
  sheet: { flex: 1, backgroundColor: c.surface },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 16 },
  sheetTitle: { fontSize: 20, fontWeight: "700", color: c.onSurface },
  label: { fontSize: 13, fontWeight: "600", color: c.onSurfaceSecondary, marginBottom: 8 },
  error: { fontSize: 14, color: c.errorText, marginBottom: 12 },
  attach: { flexDirection: "row", alignItems: "center", gap: 12, borderWidth: 1.5, borderStyle: "dashed", borderColor: c.borderStrong, backgroundColor: c.brandTertiary, borderRadius: 14, padding: 14, marginBottom: 16, minHeight: 64 },
  fileCard: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.brandTertiary, borderRadius: 14, padding: 12, marginBottom: 16 },
  fileLink: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 32 },
  sectionHead: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 },
  sectionTitle: { flex: 1, fontSize: 17, fontWeight: "700", color: c.onSurface },
  sectionEmpty: { fontSize: 14, color: c.muted, marginLeft: 4 },
  shareBox: { backgroundColor: c.brandTertiary, borderRadius: 14, padding: 12, gap: 10, marginBottom: 16 },
  shareRow: { flexDirection: "row", alignItems: "center", gap: 12, minHeight: 44 },
}));
