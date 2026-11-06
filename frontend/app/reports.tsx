// Reports (Company Drive): built-in app reports plus a private folder of report files.
// For Admin, HR, Finance and Service Coordinators.
import { useState } from "react";
import { Pressable, RefreshControl, ScrollView, View } from "react-native";
import { router } from "expo-router";
import * as DocumentPicker from "expo-document-picker";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders, getApiToken, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Text } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { ConfirmSheet, Sheet } from "@/src/components/participant-sheets";
import { Button, Chip, EmptyState, ErrorState, Field, IconName, Ionicons, Loading, isoToDmy, timeAgo } from "@/src/components/ui";
import { uploadForm } from "@/src/utils/upload";
import { makeStyles, useTheme } from "@/src/theme";

const CATS = ["Finance", "Compliance", "Rostering", "Participants", "HR", "Other"];
const tok = () => encodeURIComponent(getApiToken() ?? "");
const monthAgo = () => isoToDmy(new Date(Date.now() - 29 * 86400000 + 8 * 3600000).toISOString().slice(0, 10));
const todayDmy = () => isoToDmy(new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10));

type Built = { key: string; title: string; sub: string; icon: IconName; show: boolean; go: () => void };

export default function Reports() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const { user } = useAuth();
  const acc = useQuery<any>({ queryKey: ["pm-access"], queryFn: () => api("/pm/access") });
  const files = useQuery<any[]>({ queryKey: ["report-files"], queryFn: () => api("/reports/files"), retry: false });
  const [cat, setCat] = useState("");
  const [upload, setUpload] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<any>(null);

  if (acc.isLoading || files.isLoading) return <Loading />;
  if ((files.error as any)?.status === 403) return <EmptyState icon="lock-closed-outline" title="Reports are for Admin, HR, Finance and Service Coordinators" />;
  if (files.isError) return <ErrorState message={(files.error as any)?.message ?? "Couldn't load reports."} onRetry={files.refetch} />;
  const admin = user?.role === "admin";
  const a = acc.data ?? {};
  const coord = admin || user?.user_type === ("support_coordinator" as any);
  const built: Built[] = [
    { key: "timesheets", title: "Timesheets (Excel)", sub: "Approved hours per worker, last 30 days", icon: "time-outline", show: !!(a.finance || a.rosters),
      go: () => openLink(`${API_URL}/timesheets/export?date_from=${monthAgo()}&date_to=${todayDmy()}&token=${tok()}`) },
    { key: "exceptions", title: "Clock exceptions (Excel)", sub: "Shifts and clock-in/out exceptions, last 30 days", icon: "alert-circle-outline", show: !!(a.finance || a.rosters),
      go: () => openLink(`${API_URL}/roster/report?date_from=${monthAgo()}&date_to=${todayDmy()}&token=${tok()}`) },
    { key: "forecast", title: "Budget forecast (PDF)", sub: "Funding left and run-out dates", icon: "trending-down-outline", show: !!a.finance,
      go: () => openLink(`${API_URL}/funding/forecast/pdf?token=${tok()}`) },
    { key: "invoices", title: "Invoices", sub: "Participant invoices and overdue totals", icon: "receipt-outline", show: !!a.finance, go: () => router.push("/pm/invoices") },
    { key: "compliance", title: "Staff compliance (Excel)", sub: "Policies, certificates and CPD for every staff member", icon: "shield-checkmark-outline", show: admin,
      go: () => openLink(`${API_URL}/compliance/export?token=${tok()}`) },
    { key: "caseload", title: "Case note completion (PDF)", sub: "This month's caseload report", icon: "document-text-outline", show: coord || user?.user_type === ("hr" as any),
      go: () => openLink(`${API_URL}/caseload/monthly-report/pdf?token=${tok()}`) },
    { key: "groups", title: "Participant group tasks", sub: "Who has actioned or acknowledged group tasks", icon: "checkmark-done-outline", show: coord,
      go: () => router.push("/participant-groups/compliance") },
  ].filter((b) => b.show) as Built[];
  const shown = (files.data ?? []).filter((f) => !cat || f.category === cat);

  const pick = async () => {
    const r = await DocumentPicker.getDocumentAsync({ copyToCacheDirectory: true });
    const f = r.canceled ? null : r.assets?.[0];
    if (f) setUpload({ file: f, title: f.name.replace(/\.[^.]+$/, ""), category: cat || "Other" });
  };
  const send = async () => {
    setBusy(true);
    try {
      const res = await uploadForm(`${API_URL}/reports/files`, {
        headers: authHeaders(), fields: { title: upload.title, category: upload.category },
        files: { file: { uri: upload.file.uri, name: upload.file.name, mimeType: upload.file.mimeType ?? undefined } },
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Upload failed");
      toast("Report uploaded", "success");
      setUpload(null);
      files.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setBusy(true);
    try {
      await api(`/reports/files/${removing.file_id}`, { method: "DELETE" });
      toast("Report deleted", "success");
      setRemoving(null);
      files.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <ScrollView style={styles.root} testID="reports-screen" contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24 }}
        refreshControl={<RefreshControl refreshing={files.isRefetching} onRefresh={files.refetch} tintColor={colors.brandPrimary} />}>
        <Text style={styles.section}>App reports</Text>
        {built.map((b) => (
          <Pressable key={b.key} onPress={b.go} style={styles.card} testID={`report-built-${b.key}`}>
            <View style={styles.icon}><Ionicons name={b.icon} size={20} color={colors.brandPrimary} /></View>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.title}>{b.title}</Text>
              <Text style={styles.meta}>{b.sub}</Text>
            </View>
            <Ionicons name="open-outline" size={18} color={colors.muted} />
          </Pressable>
        ))}

        <Text style={[styles.section, { marginTop: 12 }]}>Report files</Text>
        <Text style={styles.meta}>Private to Admin, HR, Finance and Service Coordinators.</Text>
        <Button label="Upload a report" icon="cloud-upload-outline" onPress={pick} testID="reports-upload" />
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
          <Chip label="All" selected={!cat} onPress={() => setCat("")} testID="reports-cat-all" />
          {CATS.map((c) => <Chip key={c} label={c} selected={cat === c} onPress={() => setCat(c)} testID={`reports-cat-${c}`} />)}
        </ScrollView>
        {!shown.length && <EmptyState icon="folder-open-outline" title="No report files yet" subtitle="Upload PDFs, spreadsheets or documents to share with the team." />}
        {shown.map((f) => (
          <Pressable key={f.file_id} onPress={() => openLink(`${API_URL}/reports/files/${f.file_id}?token=${tok()}`)} style={styles.card} testID={`report-file-${f.file_id}`}>
            <View style={styles.icon}><Ionicons name="document-outline" size={20} color={colors.accent} /></View>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.title} numberOfLines={2}>{f.title}</Text>
              <Text style={styles.meta}>{f.category} · {f.uploaded_by_name} · {timeAgo(f.created_at)}</Text>
            </View>
            {(admin || f.uploaded_by === user?.user_id) && (
              <Pressable onPress={() => setRemoving(f)} hitSlop={8} style={styles.iconBtn} accessibilityLabel={`Delete ${f.title}`} testID={`report-delete-${f.file_id}`}>
                <Ionicons name="trash-outline" size={20} color={colors.muted} />
              </Pressable>
            )}
          </Pressable>
        ))}
      </ScrollView>

      <Sheet visible={!!upload} onClose={() => !busy && setUpload(null)} title="Upload report" sub={upload?.file?.name ?? ""} testID="reports-upload-sheet">
        {upload && (
          <>
            <Field label="Title" value={upload.title} onChangeText={(v) => setUpload({ ...upload, title: v })} testID="reports-upload-title" />
            <View style={styles.chipsWrap}>
              {CATS.map((c) => <Chip key={c} label={c} selected={upload.category === c} onPress={() => setUpload({ ...upload, category: c })} testID={`reports-upload-cat-${c}`} />)}
            </View>
            <Button label="Upload" icon="cloud-upload-outline" loading={busy} disabled={busy} onPress={send} testID="reports-upload-send" />
          </>
        )}
        <Button label="Cancel" variant="ghost" onPress={() => setUpload(null)} />
      </Sheet>
      <ConfirmSheet visible={!!removing} title={`Delete ${removing?.title ?? ""}?`} sub="This removes the file for everyone." confirmLabel="Delete"
        busy={busy} onConfirm={remove} onClose={() => setRemoving(null)} />
    </>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  card: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: c.surface, borderRadius: 14, padding: 12, minHeight: 60 },
  icon: { width: 40, height: 40, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  chips: { flexDirection: "row", gap: 8 },
  chipsWrap: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  section: { fontSize: 13, fontWeight: "700", color: c.muted, textTransform: "uppercase" },
  title: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
}));
