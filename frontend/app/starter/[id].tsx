import { useCallback, useState } from "react";
import { View } from "react-native";
import { Text } from "@/src/components/text";
import { useFocusEffect, useLocalSearchParams } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { CheckinCard } from "@/src/components/checkin-card";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, ConfirmSheet, EmptyState, ErrorState, Field, Ionicons, Loading, dmyToIso, formatDate } from "@/src/components/ui";
import { groupLabel } from "@/src/groups";
import { makeStyles, useTheme } from "@/src/theme";

export default function StarterProgress() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const key = ["starter-user", id];
  const q = useQuery<any>({ queryKey: key, queryFn: () => api(`/starter-checklist/user/${id}`), enabled: user?.role === "admin" && !!id });
  const [form, setForm] = useState({ date: "", time: "", location: "", note: "" });
  const [saving, setSaving] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState<string | null>(null);
  const cal = useQuery<any>({ queryKey: ["calendar-status"], queryFn: () => api("/integrations/outlook-calendar/status"), enabled: user?.role === "admin" });
  useFocusEffect(
    useCallback(() => {
      cal.refetch();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []),
  );

  if (user?.role !== "admin") return <EmptyState icon="lock-closed-outline" title="Admins only" />;
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load this checklist." onRetry={() => q.refetch()} />;
  const { user: s, items, done, total, completed_at, checkins } = q.data;
  const pct = total ? Math.round((done / total) * 100) : 0;

  const cancel = async (eventId: string) => {
    try {
      await api(`/starter-checklist/user/${id}/checkin/${eventId}`, { method: "DELETE" });
      toast("Check-in cancelled", "success");
      setConfirmCancel(null);
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["events"] });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const book = async () => {
    const iso = dmyToIso(form.date);
    if (!iso) return toast("Enter the date as dd-mm-yyyy", "error");
    setSaving(true);
    try {
      const r = await api(`/starter-checklist/user/${id}/checkin`, { method: "POST", body: { ...form, date: iso } });
      const first = s.name.split(" ")[0];
      toast(
        r.calendar === "sent" ? `Check-in booked and Outlook invite sent to ${first}.` : r.calendar === "failed" ? `Check-in booked. ${first} was notified, but the calendar invite failed.` : `Check-in booked. ${first} has been notified.`,
        r.calendar === "failed" ? "info" : "success",
      );
      setForm({ date: "", time: "", location: "", note: "" });
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["events"] });
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <KeyboardAwareScrollView
      style={styles.root}
      contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
      keyboardShouldPersistTaps="handled"
      bottomOffset={24}
      testID="starter-progress-screen"
    >
      <View style={styles.hero}>
        <Avatar name={s.name} picture={s.picture} size={48} />
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={styles.name}>{s.name}</Text>
          <Text style={styles.sub}>{groupLabel(s.staff_group) || "No group"}</Text>
          <View style={styles.bar}>
            <View style={[styles.barFill, { width: `${pct}%` }]} />
          </View>
          <Text style={styles.sub} testID="starter-progress-count">
            {done} of {total} steps done{completed_at ? ` · finished ${formatDate(completed_at)}` : ""}
          </Text>
        </View>
      </View>

      <Text style={styles.section}>Checklist</Text>
      {items.map((it: any, i: number) => (
        <View key={it.key} style={styles.item} testID={`starter-admin-item-${it.key}`}>
          <Ionicons name={it.done ? "checkmark-circle" : "ellipse-outline"} size={24} color={it.done ? colors.success : colors.muted} />
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={[styles.itemTitle, it.done && { color: colors.muted }]}>
              {i + 1}. {it.title}
            </Text>
            <Text style={[styles.itemSub, !it.done && { color: colors.warningText }]}>
              {it.type === "policies"
                ? `${it.progress[0]} of ${it.progress[1]} acknowledged`
                : it.type === "certificate"
                  ? it.missing?.length ? `Still needed: ${it.missing.join(", ")}` : `${it.progress[0]} uploaded`
                  : it.done ? `Submitted ${formatDate(it.done_at)}` : "Not submitted yet"}
            </Text>
          </View>
        </View>
      ))}

      <Text style={styles.section}>Check-ins</Text>
      {checkins.length === 0 ? (
        <Text style={styles.sub}>No check-ins booked yet.</Text>
      ) : (
        checkins.map((c: any) => (
          <CheckinCard key={c.event_id} c={c} userId={id} onChanged={() => qc.invalidateQueries({ queryKey: key })} onCancel={() => setConfirmCancel(c.event_id)} />
        ))
      )}

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Book a check-in</Text>
        {cal.data?.connected && (
          <Text style={styles.itemSub} testID="calendar-connected">An Outlook invite will be sent from your calendar automatically.</Text>
        )}
        <Field label="Date (dd-mm-yyyy)" value={form.date} onChangeText={(v) => setForm({ ...form, date: v })} placeholder="e.g. 15-07-2026" keyboardType="numbers-and-punctuation" testID="checkin-date" />
        <Field label="Time" value={form.time} onChangeText={(v) => setForm({ ...form, time: v })} placeholder="e.g. 10:00am" testID="checkin-time" />
        <Field label="Location" value={form.location} onChangeText={(v) => setForm({ ...form, location: v })} placeholder="e.g. Office or Teams" testID="checkin-location" />
        <Field label="Note" value={form.note} onChangeText={(v) => setForm({ ...form, note: v })} placeholder="Optional" multiline testID="checkin-note" />
        <Button label="Book check-in" icon="calendar" loading={saving} disabled={!form.date.trim()} onPress={book} testID="checkin-book-button" />
      </View>
      <ConfirmSheet
        visible={confirmCancel !== null}
        title="Cancel this check-in?"
        message={`${s.name.split(" ")[0]} will be notified, and any Outlook invite will be cancelled. Notes on it are deleted too.`}
        confirmLabel="Cancel check-in"
        onConfirm={() => confirmCancel && cancel(confirmCancel)}
        onClose={() => setConfirmCancel(null)}
      />
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  hero: { flexDirection: "row", gap: 12, alignItems: "center", backgroundColor: c.surface, borderRadius: 16, padding: 16 },
  name: { fontSize: 18, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  bar: { height: 8, borderRadius: 4, backgroundColor: c.brandTertiary, overflow: "hidden", marginVertical: 4 },
  barFill: { height: 8, borderRadius: 4, backgroundColor: c.brandPrimary },
  section: { fontSize: 13, fontWeight: "700", color: c.muted, textTransform: "uppercase", marginTop: 8 },
  item: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: c.surface, borderRadius: 14, padding: 12 },
  itemTitle: { fontSize: 15, fontWeight: "600", color: c.onSurface },
  itemSub: { fontSize: 13, color: c.onSurfaceSecondary },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 16, gap: 12, marginTop: 8 },
  cardTitle: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  cancelBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  calBox: { backgroundColor: c.surfaceSecondary, borderRadius: 12, padding: 12, gap: 10 },
}));
