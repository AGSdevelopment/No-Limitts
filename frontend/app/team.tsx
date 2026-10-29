import { useState } from "react";
import * as Clipboard from "expo-clipboard";
import * as DocumentPicker from "expo-document-picker";
import { ActivityIndicator, FlatList, Modal, Pressable, ScrollView, View } from "react-native";
import { Text } from "@/src/components/text";
import { Stack, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders, getApiToken, openLink } from "@/src/api";
import { uploadForm } from "@/src/utils/upload";
import { useAuth } from "@/src/auth";
import { GroupPickerSheet } from "@/src/components/group-picker";
import { MilestoneBadge } from "@/src/components/milestone-badge";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, ConfirmSheet, EmptyState, ErrorState, Field, Ionicons, Loading, Pill } from "@/src/components/ui";
import { USER_TYPES, typeLabel } from "@/src/groups";
import { makeStyles, useTheme } from "@/src/theme";

export default function Team() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery<any[]>({ queryKey: ["users"], queryFn: () => api("/users") });
  const isAdmin = user?.role === "admin";
  const isExec = user?.user_type === "executive";
  const typeOptions = USER_TYPES.filter((t) => isExec || t.key !== "executive");
  const [typeFor, setTypeFor] = useState<any>(null);
  const [typeSel, setTypeSel] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", user_type: "support_worker" });
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<{ name: string; email: string; password: string } | null>(null);
  const [confirm, setConfirm] = useState<{ kind: "reset" | "remove" | "resend"; u: any } | null>(null);
  const [copied, setCopied] = useState(false);
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState<{ added: any[]; skipped: any[] } | null>(null);

  const importSheet = async () => {
    const pick = await DocumentPicker.getDocumentAsync({ copyToCacheDirectory: true,
      type: ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv", "text/comma-separated-values", "application/vnd.ms-excel"] });
    const f = pick.canceled ? null : pick.assets?.[0];
    if (!f) return;
    setImporting(true);
    try {
      const res = await uploadForm(`${API_URL}/users/import`, { headers: authHeaders(), files: { file: { uri: f.uri, name: f.name, mimeType: f.mimeType ?? undefined } } });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Import failed");
      setImported(body);
      refresh();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setImporting(false);
    }
  };

  const copyLogin = async () => {
    if (!issued) return;
    try {
      await Clipboard.setStringAsync(
        `Hi ${issued.name.split(" ")[0]}, here's your No Limitts app login:\nEmail: ${issued.email}\nTemporary password: ${issued.password}\n` +
        `Open the No Limitts app, sign in under "Support Workers", then choose your own password.`
      );
      setCopied(true);
      toast("Login details copied", "success");
    } catch {
      toast("Couldn't copy. Press and hold the password to copy it instead.", "error");
    }
  };

  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });
  const canManage = (u: any) => isAdmin && u.user_id !== user?.user_id && (isExec || u.user_type !== "executive");

  const message = async (u: any) => {
    try {
      const conv = await api("/dms", { method: "POST", body: { user_id: u.user_id } });
      router.push({ pathname: "/chat/[id]", params: { id: conv.conversation_id, name: u.name } });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const saveType = async () => {
    if (!typeFor || !typeSel[0]) return;
    setBusy(true);
    try {
      const r = await api(`/users/${typeFor.user_id}/type`, { method: "PATCH", body: { user_type: typeSel[0] } });
      refresh();
      toast(`${typeFor.name} is now ${typeLabel(typeSel[0])}`, "success");
      const who = typeFor;
      setTypeFor(null);
      if (r.temporary_password) setTimeout(() => setIssued({ name: who.name, email: who.email, password: r.temporary_password }), 450);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const addStaff = async () => {
    setBusy(true);
    try {
      const r = await api("/users", { method: "POST", body: form });
      refresh();
      setAdding(false);
      setForm({ name: "", email: "", user_type: "support_worker" });
      // let the add sheet finish closing first (iOS won't open a second modal mid-dismiss)
      if (r.temporary_password) setTimeout(() => setIssued({ name: r.user.name, email: r.user.email, password: r.temporary_password }), 450);
      else toast(`${r.user.name} added. They can sign in with Microsoft now.`, "success");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const doConfirm = async () => {
    if (!confirm) return;
    const { kind, u } = confirm;
    setConfirm(null);
    try {
      if (kind === "reset") {
        const r = await api(`/users/${u.user_id}/reset-password`, { method: "POST" });
        setTimeout(() => setIssued({ name: u.name, email: u.email, password: r.temporary_password }), 450);
      } else if (kind === "resend") {
        const r = await api(`/users/${u.user_id}/resend-welcome`, { method: "POST" });
        toast(r.emailed ? `Welcome email sent to ${u.email}` : "No real email address, so nothing was sent", r.emailed ? "success" : "info");
        if (r.temporary_password) setTimeout(() => setIssued({ name: u.name, email: u.email, password: r.temporary_password }), 450);
      } else {
        await api(`/users/${u.user_id}`, { method: "DELETE" });
        toast(`${u.name} removed`, "info");
      }
      refresh();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <View style={styles.root} testID="team-screen">
      {isAdmin && (
        <Stack.Screen options={{ headerRight: () => (
          <View style={{ flexDirection: "row" }}>
            <Pressable onPress={importSheet} disabled={importing} style={styles.headerBtn} accessibilityLabel="Import staff from a spreadsheet" testID="team-import-button">
              {importing ? <ActivityIndicator color={colors.brandPrimary} /> : <Ionicons name="cloud-upload-outline" size={22} color={colors.brandPrimary} />}
            </Pressable>
            <Pressable onPress={() => setAdding(true)} style={styles.headerBtn} accessibilityLabel="Add staff member" testID="team-add-button">
              <Ionicons name="person-add-outline" size={22} color={colors.brandPrimary} />
            </Pressable>
          </View>
        ) }} />
      )}
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Could not load team." onRetry={() => q.refetch()} />
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(u) => u.user_id}
          contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          ListEmptyComponent={<EmptyState icon="people-outline" title="No one here yet" subtitle={isAdmin ? "Tap + to add your first staff member." : undefined} />}
          ListHeaderComponent={isAdmin ? (
            <View style={{ gap: 6 }}>
              <Text style={styles.hint} testID="team-import-hint">
                Adding lots of staff? Tap the upload icon and pick an Excel or CSV file with columns: Name, Email, and optionally User type, Job title, Start date, Birthday. Everyone is Support Worker unless the User type says otherwise.
              </Text>
              <Pressable onPress={() => openLink(`${API_URL}/users/import-template?token=${encodeURIComponent(getApiToken() ?? "")}`)}
                style={styles.templateBtn} testID="team-import-template" accessibilityLabel="Download the staff import template">
                <Ionicons name="download-outline" size={18} color={colors.brandPrimary} />
                <Text style={styles.smallBtnText}>Download sample spreadsheet</Text>
              </Pressable>
            </View>
          ) : null}
          renderItem={({ item }) => (
            <View style={styles.row} testID={`team-member-${item.user_id}`}>
              <Avatar name={item.name} picture={item.picture} size={48} />
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={styles.name}>{item.name}{item.user_id === user?.user_id ? " (you)" : ""}</Text>
                <Text style={styles.email} numberOfLines={1}>{item.email}</Text>
                <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
                  <Pill label={typeLabel(item.user_type) || "Support Worker"} tone={item.role === "admin" ? "brand" : "muted"} />
                  {item.must_change_password && <Pill label="Password not set yet" tone="accent" />}
                  <MilestoneBadge startDate={item.start_date} compact />
                </View>
                {isAdmin && (
                  <View style={styles.actions}>
                    <Pressable testID={`team-profile-${item.user_id}`} onPress={() => router.push(`/staff/${item.user_id}`)} style={styles.smallBtn}>
                      <Text style={styles.smallBtnText}>Profile</Text>
                    </Pressable>
                    {canManage(item) && (
                      <>
                        <Pressable testID={`team-type-button-${item.user_id}`} onPress={() => { setTypeSel([item.user_type ?? "support_worker"]); setTypeFor(item); }} style={styles.smallBtn}>
                          <Text style={styles.smallBtnText}>Change type</Text>
                        </Pressable>
                        {item.user_type === "support_worker" && (
                          <Pressable testID={`team-reset-${item.user_id}`} onPress={() => setConfirm({ kind: "reset", u: item })} style={styles.smallBtn}>
                            <Text style={styles.smallBtnText}>Reset password</Text>
                          </Pressable>
                        )}
                        <Pressable testID={`team-resend-${item.user_id}`} onPress={() => setConfirm({ kind: "resend", u: item })} style={styles.smallBtn}>
                          <Text style={styles.smallBtnText}>Resend welcome</Text>
                        </Pressable>
                        <Pressable testID={`team-remove-${item.user_id}`} onPress={() => setConfirm({ kind: "remove", u: item })} style={styles.smallBtn}>
                          <Text style={[styles.smallBtnText, { color: colors.error }]}>Remove</Text>
                        </Pressable>
                      </>
                    )}
                  </View>
                )}
              </View>
              {item.user_id !== user?.user_id && (
                <Pressable testID={`team-message-${item.user_id}`} onPress={() => message(item)} style={styles.iconBtn} accessibilityLabel={`Message ${item.name}`}>
                  <Ionicons name="chatbubble-outline" size={20} color={colors.brandPrimary} />
                </Pressable>
              )}
            </View>
          )}
        />
      )}

      <GroupPickerSheet visible={!!typeFor} title={`User type for ${typeFor?.name ?? ""}`} subtitle="Controls admin tools, forms they see and how they sign in."
        multi={false} selected={typeSel} onChange={setTypeSel} onClose={() => setTypeFor(null)} onSave={saveType} saving={busy}
        emptyLabel="" hideEmpty options={typeOptions} />

      <Modal visible={adding} transparent animationType="slide" onRequestClose={() => setAdding(false)}>
        <Pressable style={styles.scrim} onPress={() => setAdding(false)} />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID="team-add-sheet">
          <Text style={styles.sheetTitle}>Add staff member</Text>
          <Field label="Full name" value={form.name} onChangeText={(v) => setForm({ ...form, name: v })} testID="team-add-name" />
          <Field label="Email" value={form.email} onChangeText={(v) => setForm({ ...form, email: v })} autoCapitalize="none" autoCorrect={false}
            keyboardType="email-address" placeholder="Their Microsoft work email for office staff" testID="team-add-email" />
          <View style={styles.typeRow}>
            {typeOptions.map((t) => (
              <Pressable key={t.key} onPress={() => setForm({ ...form, user_type: t.key })} testID={`team-add-type-${t.key}`}
                style={[styles.typeChip, form.user_type === t.key && { backgroundColor: colors.brandPrimary }]}>
                <Text style={[styles.typeChipText, form.user_type === t.key && { color: colors.onBrandPrimary }]}>{t.label}</Text>
              </Pressable>
            ))}
          </View>
          <Text style={styles.hint}>{USER_TYPES.find((t) => t.key === form.user_type)?.hint}</Text>
          <Button label="Add" loading={busy} disabled={!form.name.trim() || !form.email.trim()} onPress={addStaff} testID="team-add-save" />
          <Button label="Cancel" variant="ghost" onPress={() => setAdding(false)} testID="team-add-cancel" />
        </View>
      </Modal>

      <Modal visible={!!issued} transparent animationType="fade" onRequestClose={() => setIssued(null)}>
        <View style={styles.center}>
          <View style={styles.dialog} testID="team-temp-password">
            <Ionicons name="key-outline" size={28} color={colors.brandPrimary} />
            <Text style={styles.sheetTitle}>Login for {issued?.name}</Text>
            <Text style={styles.hint}>Share these with them. They&apos;ll choose their own password the first time they sign in. This password is only shown once.</Text>
            <View style={styles.cred}>
              <Text style={styles.credLabel}>Email</Text>
              <Text selectable style={styles.credValue}>{issued?.email}</Text>
              <Text style={styles.credLabel}>Temporary password</Text>
              <Text selectable style={[styles.credValue, { fontSize: 20 }]} testID="team-temp-password-value">{issued?.password}</Text>
            </View>
            <Button label={copied ? "Copied!" : "Copy login details"} icon={copied ? "checkmark" : "copy-outline"} variant="secondary" onPress={copyLogin} testID="team-temp-password-copy" />
            <Button label="Done" onPress={() => { setIssued(null); setCopied(false); }} testID="team-temp-password-done" />
          </View>
        </View>
      </Modal>

      <ConfirmSheet visible={!!confirm}
        title={confirm?.kind === "reset" ? `Reset ${confirm?.u.name}'s password?` : confirm?.kind === "resend" ? `Resend ${confirm?.u.name}'s welcome email?` : `Remove ${confirm?.u.name}?`}
        message={confirm?.kind === "reset" ? "They'll be signed out and get a new temporary password from you."
          : confirm?.kind === "resend" ? (confirm?.u.user_type === "support_worker" ? "They'll get a fresh temporary password by email. Their old password stops working and they'll be signed out." : "They'll get the email again with how to sign in with Microsoft.")
          : "They'll lose access to No Limitts straight away."}
        confirmLabel={confirm?.kind === "reset" ? "Reset password" : confirm?.kind === "resend" ? "Send email" : "Remove"} onConfirm={doConfirm} onClose={() => setConfirm(null)} />

      <Modal visible={!!imported} transparent animationType="fade" onRequestClose={() => setImported(null)}>
        <View style={styles.center}>
          <View style={[styles.dialog, { maxHeight: "80%" }]} testID="team-import-result">
            <Text style={styles.sheetTitle}>Import finished</Text>
            <Text style={styles.hint} testID="team-import-summary">
              {imported?.added.length ?? 0} added{imported?.skipped.length ? ` · ${imported.skipped.length} skipped` : ""}.{" "}
              {imported?.added.some((a) => a.emailed) ? "Welcome emails with sign-in steps are on their way. " : ""}
              {imported?.added.some((a) => !a.emailed) ? "People marked ✉︎✗ have no real email address: use Resend welcome or Reset password to give them a login." : ""}
            </Text>
            <ScrollView style={{ maxHeight: 320 }} contentContainerStyle={{ gap: 6 }}>
              {imported?.added.map((a) => (
                <Text key={a.email} style={styles.importRow}>✓ {a.name} · {typeLabel(a.user_type)}{a.emailed ? "" : " · ✉︎✗"}</Text>
              ))}
              {imported?.skipped.map((s) => (
                <Text key={`${s.row}`} style={[styles.importRow, { color: colors.errorText }]}>Row {s.row}: {s.name || s.email || "blank"}: {s.reason}</Text>
              ))}
            </ScrollView>
            <Button label="Done" onPress={() => setImported(null)} testID="team-import-done" />
          </View>
        </View>
      </Modal>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  row: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 14, padding: 14 },
  name: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  email: { fontSize: 13, color: c.muted },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  headerBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  actions: { flexDirection: "row", gap: 8, flexWrap: "wrap", marginTop: 4 },
  smallBtn: { minHeight: 44, paddingHorizontal: 12, borderRadius: 22, backgroundColor: c.brandTertiary, justifyContent: "center" },
  smallBtnText: { fontSize: 13, fontWeight: "600", color: c.onBrandTertiary },
  scrim: { flex: 1, backgroundColor: c.scrim },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 24, gap: 12 },
  sheetTitle: { fontSize: 20, fontWeight: "700", color: c.onSurface },
  typeRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  typeChip: { minHeight: 40, paddingHorizontal: 14, borderRadius: 20, backgroundColor: c.brandTertiary, justifyContent: "center" },
  typeChipText: { fontSize: 14, fontWeight: "600", color: c.onBrandTertiary },
  hint: { fontSize: 13, color: c.muted, lineHeight: 18 },
  center: { flex: 1, backgroundColor: c.scrim, alignItems: "center", justifyContent: "center", padding: 24 },
  dialog: { backgroundColor: c.surface, borderRadius: 20, padding: 24, gap: 12, width: "100%", maxWidth: 420 },
  cred: { backgroundColor: c.surfaceSecondary, borderRadius: 12, padding: 14, gap: 4 },
  credLabel: { fontSize: 12, fontWeight: "700", color: c.muted },
  credValue: { fontSize: 16, fontWeight: "700", color: c.onSurface, marginBottom: 6 },
  importRow: { fontSize: 14, color: c.onSurface },
  templateBtn: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", minHeight: 44, paddingHorizontal: 14, borderRadius: 22, backgroundColor: c.brandTertiary, marginBottom: 4 },
}));
