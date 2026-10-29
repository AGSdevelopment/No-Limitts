import { useState } from "react";
import { FlatList, Modal, Pressable, View } from "react-native";
import { Text } from "@/src/components/text";
import { Stack, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
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
  const [confirm, setConfirm] = useState<{ kind: "reset" | "remove"; u: any } | null>(null);

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
          <Pressable onPress={() => setAdding(true)} style={styles.headerBtn} accessibilityLabel="Add staff member" testID="team-add-button">
            <Ionicons name="person-add-outline" size={22} color={colors.brandPrimary} />
          </Pressable>
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
            <Button label="Done" onPress={() => setIssued(null)} testID="team-temp-password-done" />
          </View>
        </View>
      </Modal>

      <ConfirmSheet visible={!!confirm}
        title={confirm?.kind === "reset" ? `Reset ${confirm?.u.name}'s password?` : `Remove ${confirm?.u.name}?`}
        message={confirm?.kind === "reset" ? "They'll be signed out and get a new temporary password from you." : "They'll lose access to No Limitts straight away."}
        confirmLabel={confirm?.kind === "reset" ? "Reset password" : "Remove"} onConfirm={doConfirm} onClose={() => setConfirm(null)} />
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
}));
