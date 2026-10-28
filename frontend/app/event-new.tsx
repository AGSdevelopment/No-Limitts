import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { PlaceChips } from "@/src/components/place-chips";
import { useToast } from "@/src/components/toast";
import { Button, Chip, Field, dmyToIso } from "@/src/components/ui";
import { makeStyles } from "@/src/theme";

export const CATERING = ["Food & drink provided", "BYO", "To be arranged"];
const REPEATS = [
  { key: "", label: "Doesn't repeat" },
  { key: "weekly", label: "Weekly" },
  { key: "fortnightly", label: "Fortnightly" },
  { key: "monthly", label: "Monthly" },
];

export default function NewEvent() {
  const router = useRouter();
  const { edit, title: preTitle, location: preLocation, description: preDescription } = useLocalSearchParams<{ edit?: string; title?: string; location?: string; description?: string }>();
  const existing = useQuery<any>({ queryKey: ["event", edit], queryFn: () => api(`/events/${edit}`), enabled: !!edit });
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const toast = useToast();
  const qc = useQueryClient();
  const [f, setF] = useState({ title: preTitle ?? "", date: "", time: "", location: preLocation ?? "", description: preDescription ?? "", catering: "", conditions: "", capacity: "", repeat: "", occurrences: 4 });
  const [saving, setSaving] = useState(false);
  const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });

  useEffect(() => {
    const e = existing.data;
    if (e) {
      setF((p) => ({ ...p, title: e.title, date: e.date.split("-").reverse().join("-"), time: e.time ?? "", location: e.location ?? "", description: e.description ?? "", catering: e.catering ?? "", conditions: e.conditions ?? "", capacity: e.capacity ? String(e.capacity) : "" }));
    }
  }, [existing.data]);

  const saveEdit = async (iso: string, cap: number | null) => {
    setSaving(true);
    try {
      const { title, time, location, description, catering, conditions } = f;
      await api(`/events/${edit}`, { method: "PATCH", body: { title, time, location, description, catering, conditions, date: iso, capacity: cap, clear_capacity: cap === null } });
      qc.invalidateQueries({ queryKey: ["event", edit] });
      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast("Event updated. Everyone who replied has been told.", "success");
      router.back();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const submit = async () => {
    if (!f.title.trim()) return toast("Give the event a name", "error");
    const iso = dmyToIso(f.date);
    if (!iso) return toast("Enter the date as dd-mm-yyyy", "error");
    const cap = f.capacity.trim() ? parseInt(f.capacity, 10) : null;
    if (cap !== null && (!cap || cap < 1)) return toast("Places must be a number above 0", "error");
    if (edit) return saveEdit(iso, cap);
    setSaving(true);
    try {
      const ev = await api("/events", { method: "POST", body: { ...f, date: iso, capacity: cap, occurrences: f.repeat ? f.occurrences : 1 } });
      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast(ev.created > 1 ? `${ev.created} events created. Everyone has been invited to RSVP.` : "Event created. Everyone has been invited to RSVP.", "success");
      router.replace(`/event/${ev.event_id}`);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <KeyboardAwareScrollView style={styles.root} contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 24 }} keyboardShouldPersistTaps="handled" bottomOffset={24} testID="event-new-screen">
      <Stack.Screen options={{ title: edit ? "Edit event" : "New event" }} />
      <Text style={styles.intro}>{edit ? "Everyone who replied will be told what changed." : "Create an event for the whole team. Everyone gets an invite and can RSVP."}</Text>
      <Field label="Event name" value={f.title} onChangeText={set("title")} placeholder="e.g. End of year BBQ" testID="event-title-input" />
      <Field label="Date (dd-mm-yyyy)" value={f.date} onChangeText={set("date")} placeholder="e.g. 12-12-2026" keyboardType="numbers-and-punctuation" testID="event-date-input" />
      <Field label="Time" value={f.time} onChangeText={set("time")} placeholder="e.g. 5:30pm" testID="event-time-input" />
      <Field label="Location" value={f.location} onChangeText={set("location")} placeholder="e.g. Kings Park, Perth" testID="event-location-input" style={{ marginBottom: 8 }} />
      <PlaceChips selected={f.location} onPick={(v) => setF({ ...f, location: v })} testID="event-place" />
      <Field label="Purpose" value={f.description} onChangeText={set("description")} placeholder="What's it for? e.g. Celebrate the year together" multiline testID="event-purpose-input" />
      <Text style={styles.label}>Food & drink</Text>
      <View style={styles.chips}>
        {CATERING.map((c) => (
          <Chip key={c} label={c} selected={f.catering === c} onPress={() => setF({ ...f, catering: f.catering === c ? "" : c })} testID={`event-catering-${c}`} />
        ))}
      </View>
      <Field label="Other details or conditions" value={f.conditions} onChangeText={set("conditions")} placeholder="e.g. Bring a plate to share, partners welcome" multiline testID="event-conditions-input" />
      <Field label="Places available (optional)" value={f.capacity} onChangeText={set("capacity")} placeholder="Leave empty for unlimited; extra people join a waitlist" keyboardType="number-pad" testID="event-capacity-input" />
      {!edit && <Text style={styles.label}>Repeats</Text>}
      {!edit && (
      <View style={styles.chips}>
        {REPEATS.map((r) => (
          <Chip key={r.key} label={r.label} selected={f.repeat === r.key} onPress={() => setF({ ...f, repeat: r.key })} testID={`event-repeat-${r.key || "none"}`} />
        ))}
      </View>
      )}
      {!!f.repeat && !edit && (
        <>
          <Text style={styles.label}>How many times in total?</Text>
          <View style={styles.chips}>
            {[2, 4, 6, 8, 12].map((n) => (
              <Chip key={n} label={`${n}`} selected={f.occurrences === n} onPress={() => setF({ ...f, occurrences: n })} testID={`event-occurrences-${n}`} />
            ))}
          </View>
        </>
      )}
      <Button label={edit ? "Save changes" : "Create event"} icon="calendar" loading={saving} onPress={submit} testID="event-create-button" />
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  intro: { fontSize: 14, color: c.onSurfaceSecondary, marginBottom: 16, lineHeight: 20 },
  label: { fontSize: 14, fontWeight: "600", color: c.onSurfaceSecondary, marginBottom: 8 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 16 },
}));
