import { useState } from "react";
import { Pressable, Text, View } from "react-native";
import { useQueryClient } from "@tanstack/react-query";

import { api } from "@/src/api";
import { PlaceChips } from "@/src/components/place-chips";
import { useToast } from "@/src/components/toast";
import { Button, Chip, Field, Ionicons, dmyToIso, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

// Poll the team on dates or venues; the organiser locks in the winner.
export function EventPoll({ ev, isOrganiser }: { ev: any; isOrganiser: boolean }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [kind, setKind] = useState<"date" | "venue">("date");
  const [options, setOptions] = useState(["", ""]);
  const [busy, setBusy] = useState(false);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["event", ev.event_id] });
    qc.invalidateQueries({ queryKey: ["events"] });
  };
  const call = async (path: string, body?: any, msg?: string) => {
    setBusy(true);
    try {
      await api(path, { method: "POST", body });
      refresh();
      if (msg) toast(msg, "success");
      return true;
    } catch (e: any) {
      toast(e.message, "error");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    const filled = options.map((o) => o.trim()).filter(Boolean);
    let opts = filled;
    if (kind === "date") {
      opts = filled.map((o) => dmyToIso(o) ?? "");
      if (opts.some((o) => !o)) return toast("Enter dates as dd-mm-yyyy", "error");
    }
    if (opts.length < 2) return toast("Add at least 2 options", "error");
    if (await call(`/events/${ev.event_id}/poll`, { kind, options: opts }, "Poll started. Everyone has been asked to vote.")) setCreating(false);
  };

  const poll = ev.poll;
  const label = (o: any) => (poll?.kind === "date" ? formatDate(o.label) : o.label);
  const top = poll ? Math.max(...poll.options.map((o: any) => o.votes), 0) : 0;

  if (!poll) {
    if (!isOrganiser || ev.date < new Date().toLocaleDateString("en-CA", { timeZone: "Australia/Perth" })) return null;
    return (
      <View style={styles.card} testID="event-poll-create">
        <Text style={styles.section}>Poll the team</Text>
        {!creating ? (
          <Button label="Start a date or venue poll" icon="stats-chart-outline" variant="secondary" onPress={() => setCreating(true)} testID="event-poll-start" />
        ) : (
          <View style={{ gap: 10 }}>
            <View style={styles.chips}>
              <Chip label="Dates" selected={kind === "date"} onPress={() => setKind("date")} testID="event-poll-kind-date" />
              <Chip label="Venues" selected={kind === "venue"} onPress={() => setKind("venue")} testID="event-poll-kind-venue" />
            </View>
            {options.map((o, i) => (
              <Field key={i} label={`Option ${i + 1}`} value={o} onChangeText={(v) => setOptions(options.map((x, j) => (j === i ? v : x)))} placeholder={kind === "date" ? "dd-mm-yyyy" : "e.g. The Royal Hotel"} testID={`event-poll-option-${i}`} style={{ marginBottom: 0 }} />
            ))}
            {kind === "venue" && (
              <PlaceChips
                testID="event-poll-place"
                onPick={(v) => {
                  if (options.includes(v)) return;
                  const i = options.findIndex((o) => !o.trim());
                  if (i >= 0) setOptions(options.map((x, j) => (j === i ? v : x)));
                  else if (options.length < 6) setOptions([...options, v]);
                  else toast("Up to 6 options", "error");
                }}
              />
            )}
            {options.length < 6 && <Button label="Add another option" icon="add" variant="ghost" onPress={() => setOptions([...options, ""])} testID="event-poll-add-option" />}
            <View style={styles.row}>
              <Button label="Cancel" variant="ghost" onPress={() => setCreating(false)} style={{ flex: 1 }} testID="event-poll-cancel" />
              <Button label="Start poll" loading={busy} onPress={create} style={{ flex: 1 }} testID="event-poll-submit" />
            </View>
          </View>
        )}
      </View>
    );
  }

  return (
    <View style={styles.card} testID="event-poll">
      <Text style={styles.section}>{poll.closed ? "Poll result" : `Vote on the ${poll.kind === "date" ? "date" : "venue"}`}</Text>
      {!poll.closed && <Text style={styles.meta}>Tap every option that works for you.</Text>}
      {poll.options.map((o: any) => {
        const winner = poll.closed && poll.locked_option_id === o.option_id;
        return (
          <View key={o.option_id} style={{ gap: 6 }}>
            <Pressable
              disabled={poll.closed || busy}
              onPress={() => call(`/events/${ev.event_id}/poll/${o.option_id}/vote`)}
              style={[styles.option, (o.voted || winner) && { borderColor: colors.brandPrimary, backgroundColor: colors.brandTertiary }]}
              testID={`event-poll-vote-${o.option_id}`}
            >
              <Ionicons name={winner ? "trophy" : o.voted ? "checkbox" : "square-outline"} size={20} color={colors.brandPrimary} />
              <Text style={styles.optionLabel}>{label(o)}</Text>
              <Text style={[styles.count, o.votes === top && top > 0 && { color: colors.brandPrimary }]}>{o.votes}</Text>
            </Pressable>
            {!!o.voters.length && <Text style={styles.meta}>{o.voters.join(", ")}</Text>}
            {isOrganiser && !poll.closed && (
              <Button label={`Lock in ${label(o)}`} variant="ghost" onPress={() => call(`/events/${ev.event_id}/poll/${o.option_id}/lock`, undefined, "Locked in. Everyone has been told.")} testID={`event-poll-lock-${o.option_id}`} />
            )}
          </View>
        );
      })}
    </View>
  );
}

// Organiser ticks who actually turned up.
export function EventAttendance({ ev, isOrganiser }: { ev: any; isOrganiser: boolean }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [picked, setPicked] = useState<string[]>((ev.attended ?? []).map((a: any) => a.user_id));
  const [saving, setSaving] = useState(false);
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Australia/Perth" });
  if (ev.date > today) return null;
  const people: { user_id: string; name: string }[] = [...(ev.rsvps ?? []), ...(ev.attended ?? [])].filter((p, i, a) => a.findIndex((x) => x.user_id === p.user_id) === i);

  if (!isOrganiser) {
    if (!ev.attended?.length) return null;
    return (
      <View style={styles.card} testID="event-attendance">
        <Text style={styles.section}>Who came · {ev.attended.length}</Text>
        <Text style={styles.meta}>{ev.attended.map((a: any) => a.name).join(", ")}</Text>
      </View>
    );
  }

  const save = async () => {
    setSaving(true);
    try {
      await api(`/events/${ev.event_id}/attendance`, { method: "PUT", body: { user_ids: picked } });
      qc.invalidateQueries({ queryKey: ["event", ev.event_id] });
      toast(`Attendance saved: ${picked.length} came`, "success");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={styles.card} testID="event-attendance">
      <Text style={styles.section}>Who turned up?</Text>
      {people.length === 0 && <Text style={styles.meta}>No one replied to this event.</Text>}
      {people.map((p) => {
        const on = picked.includes(p.user_id);
        return (
          <Pressable key={p.user_id} onPress={() => setPicked(on ? picked.filter((x) => x !== p.user_id) : [...picked, p.user_id])} style={styles.attRow} testID={`event-attend-${p.user_id}`}>
            <Ionicons name={on ? "checkbox" : "square-outline"} size={22} color={on ? colors.success : colors.muted} />
            <Text style={styles.optionLabel}>{p.name}</Text>
          </Pressable>
        );
      })}
      {people.length > 0 && <Button label="Save attendance" icon="checkmark-done" loading={saving} onPress={save} testID="event-attendance-save" />}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 16, gap: 10 },
  section: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted },
  chips: { flexDirection: "row", gap: 8 },
  row: { flexDirection: "row", gap: 8 },
  option: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 48, paddingHorizontal: 12, borderRadius: 12, borderWidth: 1, borderColor: c.border },
  optionLabel: { flex: 1, fontSize: 15, fontWeight: "600", color: c.onSurface },
  count: { fontSize: 15, fontWeight: "700", color: c.muted },
  attRow: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 44 },
}));
