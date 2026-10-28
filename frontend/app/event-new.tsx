import { useState } from "react";
import { Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, Chip, Field, dmyToIso } from "@/src/components/ui";
import { makeStyles } from "@/src/theme";

export const CATERING = ["Food & drink provided", "BYO", "To be arranged"];

export default function NewEvent() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const toast = useToast();
  const qc = useQueryClient();
  const [f, setF] = useState({ title: "", date: "", time: "", location: "", description: "", catering: "", conditions: "" });
  const [saving, setSaving] = useState(false);
  const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });

  const submit = async () => {
    if (!f.title.trim()) return toast("Give the event a name", "error");
    const iso = dmyToIso(f.date);
    if (!iso) return toast("Enter the date as dd-mm-yyyy", "error");
    setSaving(true);
    try {
      const ev = await api("/events", { method: "POST", body: { ...f, date: iso } });
      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast("Event created. Everyone has been invited to RSVP.", "success");
      router.replace(`/event/${ev.event_id}`);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <KeyboardAwareScrollView style={styles.root} contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 24 }} keyboardShouldPersistTaps="handled" bottomOffset={24} testID="event-new-screen">
      <Text style={styles.intro}>Create an event for the whole team. Everyone gets an invite and can RSVP.</Text>
      <Field label="Event name" value={f.title} onChangeText={set("title")} placeholder="e.g. End of year BBQ" testID="event-title-input" />
      <Field label="Date (dd-mm-yyyy)" value={f.date} onChangeText={set("date")} placeholder="e.g. 12-12-2026" keyboardType="numbers-and-punctuation" testID="event-date-input" />
      <Field label="Time" value={f.time} onChangeText={set("time")} placeholder="e.g. 5:30pm" testID="event-time-input" />
      <Field label="Location" value={f.location} onChangeText={set("location")} placeholder="e.g. Kings Park, Perth" testID="event-location-input" />
      <Field label="Purpose" value={f.description} onChangeText={set("description")} placeholder="What's it for? e.g. Celebrate the year together" multiline testID="event-purpose-input" />
      <Text style={styles.label}>Food & drink</Text>
      <View style={styles.chips}>
        {CATERING.map((c) => (
          <Chip key={c} label={c} selected={f.catering === c} onPress={() => setF({ ...f, catering: f.catering === c ? "" : c })} testID={`event-catering-${c}`} />
        ))}
      </View>
      <Field label="Other details or conditions" value={f.conditions} onChangeText={set("conditions")} placeholder="e.g. Bring a plate to share, partners welcome" multiline testID="event-conditions-input" />
      <Button label="Create event" icon="calendar" loading={saving} onPress={submit} testID="event-create-button" />
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  intro: { fontSize: 14, color: c.onSurfaceSecondary, marginBottom: 16, lineHeight: 20 },
  label: { fontSize: 14, fontWeight: "600", color: c.onSurfaceSecondary, marginBottom: 8 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 16 },
}));
