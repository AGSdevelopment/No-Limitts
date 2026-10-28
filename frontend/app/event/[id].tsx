import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, Chip, ConfirmSheet, EmptyState, ErrorState, Field, Ionicons, Loading, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const OPTIONS = [
  { key: "going", label: "Going", icon: "checkmark-circle" },
  { key: "maybe", label: "Maybe", icon: "help-circle" },
  { key: "not_going", label: "Can't go", icon: "close-circle" },
] as const;

export default function EventDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery<any>({ queryKey: ["event", id], queryFn: () => api(`/events/${id}`), enabled: !!id });
  const [status, setStatus] = useState<string>("");
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (q.data?.my_rsvp) {
      setStatus(q.data.my_rsvp.status);
      setComment(q.data.my_rsvp.comment ?? "");
    }
  }, [q.data?.my_rsvp]);

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load this event." onRetry={() => q.refetch()} />;
  if (!q.data) return <EmptyState icon="calendar-outline" title="Event not found" />;
  const ev = q.data;
  const toneOf = (s: string) => (s === "going" ? colors.success : s === "maybe" ? colors.warningText : colors.error);

  const save = async (nextStatus = status) => {
    if (!nextStatus) return toast("Choose Going, Maybe or Can't go", "error");
    setSaving(true);
    try {
      await api(`/events/${id}/rsvp`, { method: "POST", body: { status: nextStatus, comment } });
      qc.invalidateQueries({ queryKey: ["event", id] });
      qc.invalidateQueries({ queryKey: ["events"] });
      toast("Your RSVP has been saved", "success");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const withdraw = async () => {
    try {
      await api(`/events/${id}/rsvp`, { method: "POST", body: { status: null, comment: "" } });
      setStatus("");
      setComment("");
      qc.invalidateQueries({ queryKey: ["event", id] });
      qc.invalidateQueries({ queryKey: ["events"] });
      toast("RSVP withdrawn", "info");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const remove = async () => {
    try {
      await api(`/events/${id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast("Event deleted", "success");
      if (router.canGoBack()) router.back();
      else router.replace("/events");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <KeyboardAwareScrollView style={styles.root} contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }} keyboardShouldPersistTaps="handled" bottomOffset={24} testID="event-detail-screen">
      <View style={styles.card}>
        <Text style={styles.title}>{ev.title}</Text>
        <Detail icon="calendar-outline" text={`${formatDate(ev.date)}${ev.time ? ` at ${ev.time}` : ""}`} />
        {!!ev.location && <Detail icon="location-outline" text={ev.location} />}
        {!!ev.description && <Detail icon="flag-outline" text={ev.description} />}
        {!!ev.catering && <Detail icon="restaurant-outline" text={ev.catering} />}
        {!!ev.conditions && <Detail icon="information-circle-outline" text={ev.conditions} />}
        <Text style={styles.meta}>Organised by {ev.created_by}</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.section}>Your RSVP</Text>
        <View style={styles.chips}>
          {OPTIONS.map((o) => (
            <Chip key={o.key} label={o.label} selected={status === o.key} onPress={() => setStatus(o.key)} testID={`event-rsvp-${o.key}`} />
          ))}
        </View>
        <Field label="Details (optional, everyone can see this)" value={comment} onChangeText={setComment} placeholder="e.g. Bringing a salad, +1, arriving late" multiline testID="event-rsvp-comment" style={{ marginBottom: 0 }} />
        <Button label={ev.my_rsvp ? "Update RSVP" : "Send RSVP"} icon="send" loading={saving} disabled={!status} onPress={() => save()} testID="event-rsvp-save" />
        {ev.my_rsvp && <Button label="Withdraw my RSVP" variant="ghost" onPress={withdraw} testID="event-rsvp-withdraw" />}
      </View>

      <View style={styles.card}>
        <Text style={styles.section} testID="event-rsvp-counts">
          {ev.counts.going} going · {ev.counts.maybe} maybe · {ev.counts.not_going} can&apos;t go
        </Text>
        {ev.rsvps.length === 0 && <Text style={styles.meta}>No responses yet. Be the first!</Text>}
        {ev.rsvps.map((r: any) => (
          <View key={r.user_id} style={styles.response} testID={`event-response-${r.user_id}`}>
            <Avatar name={r.name} picture={r.picture} size={36} />
            <View style={{ flex: 1 }}>
              <Text style={styles.name}>{r.name}</Text>
              <Text style={[styles.status, { color: toneOf(r.status) }]}>{OPTIONS.find((o) => o.key === r.status)?.label}</Text>
              {!!r.comment && <Text style={styles.comment}>{r.comment}</Text>}
            </View>
          </View>
        ))}
      </View>

      {ev.can_delete && !ev.checkin_for && <Button label="Delete event" icon="trash-outline" variant="ghost" onPress={() => setConfirmDelete(true)} testID="event-delete" />}
      <ConfirmSheet visible={confirmDelete} title="Delete this event?" message="Everyone who responded will be told it's cancelled." confirmLabel="Delete event" onConfirm={remove} onClose={() => setConfirmDelete(false)} />
    </KeyboardAwareScrollView>
  );
}

function Detail({ icon, text }: { icon: any; text: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.detail}>
      <Ionicons name={icon} size={18} color={colors.brandPrimary} />
      <Text style={styles.detailText}>{text}</Text>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 16, gap: 10 },
  title: { fontSize: 20, fontWeight: "700", color: c.onSurface },
  detail: { flexDirection: "row", gap: 10, alignItems: "flex-start" },
  detailText: { flex: 1, fontSize: 15, color: c.onSurface, lineHeight: 21 },
  meta: { fontSize: 13, color: c.muted },
  section: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  response: { flexDirection: "row", gap: 10, alignItems: "flex-start" },
  name: { fontSize: 15, fontWeight: "600", color: c.onSurface },
  status: { fontSize: 13, fontWeight: "700" },
  comment: { fontSize: 14, color: c.onSurfaceSecondary, marginTop: 2 },
}));
