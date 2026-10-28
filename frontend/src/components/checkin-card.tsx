import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { api } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, Chip, Field, Ionicons, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const OUTCOMES = ["On track", "Needs support", "Follow-up needed"];

// One booked check-in on the admin starter screen, with private notes + outcome.
export function CheckinCard({ c, userId, onChanged, onCancel }: { c: any; userId: string; onChanged: () => void; onCancel: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [notes, setNotes] = useState(c.notes ?? "");
  const [outcome, setOutcome] = useState(c.outcome ?? "");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await api(`/starter-checklist/user/${userId}/checkin/${c.event_id}/notes`, { method: "PUT", body: { notes, outcome } });
      toast("Check-in notes saved", "success");
      setEditing(false);
      onChanged();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const tone = c.outcome === "On track" ? colors.success : c.outcome ? colors.warningText : colors.muted;

  return (
    <View style={styles.card} testID={`starter-checkin-${c.event_id}`}>
      <View style={styles.row}>
        <Ionicons name="calendar-outline" size={22} color={colors.brandPrimary} />
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>
            {formatDate(c.date)}
            {c.time ? ` at ${c.time}` : ""}
          </Text>
          {!!(c.location || c.description) && <Text style={styles.sub}>{[c.location, c.description].filter(Boolean).join(" · ")}</Text>}
          {c.calendar === "sent" && <Text style={styles.sub}>Google Calendar invite sent</Text>}
        </View>
        <Pressable onPress={onCancel} hitSlop={8} style={styles.iconBtn} accessibilityLabel="Cancel check-in" testID={`starter-checkin-cancel-${c.event_id}`}>
          <Ionicons name="trash-outline" size={20} color={colors.error} />
        </Pressable>
      </View>

      {editing ? (
        <View style={{ gap: 10 }}>
          <Text style={styles.label}>Outcome</Text>
          <View style={styles.chips}>
            {OUTCOMES.map((o) => (
              <Chip key={o} label={o} selected={outcome === o} onPress={() => setOutcome(outcome === o ? "" : o)} testID={`checkin-outcome-${o}`} />
            ))}
          </View>
          <Field label="Notes (only admins see these)" value={notes} onChangeText={setNotes} placeholder="What was discussed, agreed actions…" multiline testID={`checkin-notes-input-${c.event_id}`} />
          <View style={styles.row}>
            <Button label="Cancel" variant="ghost" onPress={() => { setEditing(false); setNotes(c.notes ?? ""); setOutcome(c.outcome ?? ""); }} style={{ flex: 1 }} testID={`checkin-notes-cancel-${c.event_id}`} />
            <Button label="Save notes" loading={saving} onPress={save} style={{ flex: 1 }} testID={`checkin-notes-save-${c.event_id}`} />
          </View>
        </View>
      ) : c.notes || c.outcome ? (
        <Pressable onPress={() => setEditing(true)} style={styles.notesBox} testID={`checkin-notes-${c.event_id}`}>
          {!!c.outcome && <Text style={[styles.outcome, { color: tone }]}>{c.outcome}</Text>}
          {!!c.notes && <Text style={styles.notes}>{c.notes}</Text>}
          <Text style={styles.meta}>
            {c.notes_by ? `${c.notes_by} · ${formatDate(c.notes_at)}` : ""} · Tap to edit
          </Text>
        </Pressable>
      ) : (
        <Button label="Add notes & outcome" icon="create-outline" variant="secondary" onPress={() => setEditing(true)} testID={`checkin-notes-add-${c.event_id}`} />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { backgroundColor: c.surface, borderRadius: 14, padding: 12, gap: 10 },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  title: { fontSize: 15, fontWeight: "600", color: c.onSurface },
  sub: { fontSize: 13, color: c.onSurfaceSecondary },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  label: { fontSize: 13, fontWeight: "600", color: c.onSurfaceSecondary },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  notesBox: { backgroundColor: c.surfaceSecondary, borderRadius: 12, padding: 12, gap: 4 },
  outcome: { fontSize: 14, fontWeight: "700" },
  notes: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
  meta: { fontSize: 12, color: c.muted },
}));
