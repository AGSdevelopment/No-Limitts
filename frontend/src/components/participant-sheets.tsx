// Caseload sheets: add a participant, assign Support Workers, and pick a case note form to write.
import { useEffect, useState } from "react";
import { FlatList, Modal, Pressable, ScrollView, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openLink } from "@/src/api";
import { Text, TextInput } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, ErrorState, Ionicons, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export function Sheet({ visible, onClose, title, sub, children, testID }: {
  visible: boolean; onClose: () => void; title: string; sub?: string; children: React.ReactNode; testID: string;
}) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior="padding" style={{ flex: 1 }}>
        <Pressable style={styles.scrim} onPress={onClose} />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID={testID}>
          <Text style={styles.title}>{title}</Text>
          {!!sub && <Text style={styles.sub}>{sub}</Text>}
          {children}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

export function ConfirmSheet({ visible, title, sub, confirmLabel, busy, onConfirm, onClose }: {
  visible: boolean; title: string; sub: string; confirmLabel: string; busy?: boolean; onConfirm: () => void; onClose: () => void;
}) {
  return (
    <Sheet visible={visible} onClose={onClose} title={title} sub={sub} testID="confirm-sheet">
      <Button label={confirmLabel} icon="trash-outline" variant="danger" loading={busy} disabled={busy} onPress={onConfirm} testID="confirm-sheet-yes" />
      <Button label="Cancel" variant="ghost" onPress={onClose} testID="confirm-sheet-cancel" />
    </Sheet>
  );
}

export function IntroSheet({ participantId, onDone, onOpenProfile }: { participantId: string | null; onDone: () => void; onOpenProfile: (id: string) => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const q = useQuery<any>({ queryKey: ["participant", participantId], queryFn: () => api(`/participants/${participantId}`), enabled: !!participantId, retry: false });
  const [busy, setBusy] = useState(false);
  const seen = async (open: boolean) => {
    setBusy(true);
    try {
      await api(`/participants/${participantId}/intro-seen`, { method: "POST" });
    } catch {
      // Not critical: they'll just see the intro again next time
    }
    setBusy(false);
    if (open && participantId) onOpenProfile(participantId);
    onDone();
  };
  const p = q.data?.profile;
  const bits = p ? [
    { icon: "flag-outline", label: "Goals", text: p.goals },
    { icon: "hand-left-outline", label: "Support needs", text: p.support_needs },
    { icon: "chatbubbles-outline", label: "Communication", text: p.communication },
    { icon: "medkit-outline", label: "Health & alerts", text: p.health_alerts },
  ].filter((b) => b.text) : [];
  return (
    <Sheet visible={!!participantId} onClose={() => seen(false)} title={q.data ? `Meet ${q.data.name}` : "Your new participant"}
      sub="You've just been assigned to support this participant. Here's what to know before your first shift." testID="intro-sheet">
      {q.isLoading ? <Loading /> : (
        <ScrollView style={{ maxHeight: 360 }} contentContainerStyle={{ gap: 10 }}>
          {!!p?.about && <Text style={styles.introBody}>{p.about}</Text>}
          {bits.map((b) => (
            <View key={b.label} style={{ gap: 2 }}>
              <View style={styles.introHead}>
                <Ionicons name={b.icon as any} size={16} color={b.label === "Health & alerts" ? colors.errorText : colors.brandPrimary} />
                <Text style={styles.name}>{b.label}</Text>
              </View>
              <Text style={styles.introBody} numberOfLines={4}>{b.text}</Text>
            </View>
          ))}
          {!!p?.contacts?.length && (
            <Text style={styles.sub}>Key contacts: {p.contacts.map((c: any) => (c.relationship ? `${c.name} (${c.relationship})` : c.name)).join(", ")}</Text>
          )}
          {!p?.about && !bits.length && <Text style={styles.sub}>Their coordinator hasn&apos;t added profile details yet. Check their notes and handovers.</Text>}
        </ScrollView>
      )}
      <Button label="Read full profile" icon="person-circle-outline" loading={busy} onPress={() => seen(true)} testID="intro-open-profile" />
      <Button label="Got it" variant="ghost" disabled={busy} onPress={() => seen(false)} testID="intro-got-it" />
    </Sheet>
  );
}

export function NudgeButton({ participantId, worker, onDone }: { participantId: string; worker: { user_id: string; name: string; nudged_at?: string }; onDone: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const recent = !!worker.nudged_at && Date.now() - new Date(worker.nudged_at).getTime() < 24 * 3600 * 1000;
  if (recent) return <Text style={styles.sub} testID={`nudge-done-${worker.user_id}`}>Reminded</Text>;
  const send = async () => {
    setBusy(true);
    try {
      await api(`/participants/${participantId}/nudge`, { method: "POST", body: { user_id: worker.user_id } });
      toast(`Reminder sent to ${worker.name}`, "success");
      onDone();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Pressable onPress={send} disabled={busy} style={styles.nudge} accessibilityRole="button" accessibilityLabel={`Remind ${worker.name}`} testID={`nudge-${worker.user_id}`}>
      <Ionicons name="notifications-outline" size={14} color={colors.brandPrimary} />
      <Text style={styles.nudgeText}>{busy ? "Sending…" : "Remind"}</Text>
    </Pressable>
  );
}

export function hourLabel(h: number) {
  return `${h % 12 === 0 ? 12 : h % 12}:00 ${h < 12 ? "am" : "pm"}`;
}

const HOURS = [14, 15, 16, 17, 18, 19, 20, 21, 22];

export function HourSheet({ visible, current, onPick, onClose }: { visible: boolean; current: number; onPick: (h: number) => void; onClose: () => void }) {
  const styles = useStyles();
  return (
    <Sheet visible={visible} onClose={onClose} title="Case note reminder time"
      sub="When the end-of-day reminder goes out to Support Workers (Perth time). It's sent once a day." testID="hour-sheet">
      <View style={styles.hours}>
        {HOURS.map((h) => (
          <Pressable key={h} onPress={() => onPick(h)} style={[styles.hour, h === current && styles.hourOn]} accessibilityRole="button"
            accessibilityState={{ selected: h === current }} testID={`hour-${h}`}>
            <Text style={[styles.hourText, h === current && styles.hourTextOn]}>{hourLabel(h)}</Text>
          </Pressable>
        ))}
      </View>
      <Button label="Cancel" variant="ghost" onPress={onClose} testID="hour-cancel" />
    </Sheet>
  );
}

function isoDay(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function DaysOffSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const styles = useStyles();
  const toast = useToast();
  const q = useQuery<{ dates: string[] }>({ queryKey: ["days-off"], queryFn: () => api("/caseload/days-off"), enabled: visible });
  const [busy, setBusy] = useState<string | null>(null);
  const days = Array.from({ length: 28 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() + i - 7);
    return d;
  });
  const toggle = async (iso: string, on: boolean) => {
    setBusy(iso);
    try {
      await api(on ? `/caseload/days-off/${iso}` : "/caseload/days-off", on ? { method: "DELETE" } : { method: "POST", body: { date: iso } });
      await q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(null);
    }
  };
  const today = isoDay(new Date());
  return (
    <Sheet visible={visible} onClose={onClose} title="Days off"
      sub="Tap the days you're not working. They won't break your case note streak or count towards it." testID="days-off-sheet">
      {q.isLoading ? <Loading /> : (
        <ScrollView style={{ maxHeight: 360 }} contentContainerStyle={styles.hours}>
          {days.map((d) => {
            const iso = isoDay(d);
            const on = q.data?.dates.includes(iso) ?? false;
            return (
              <Pressable key={iso} onPress={() => toggle(iso, on)} disabled={busy === iso} style={[styles.hour, on && styles.hourOn]}
                accessibilityRole="checkbox" accessibilityState={{ checked: on }} testID={`day-off-${iso}`}>
                <Text style={[styles.hourText, on && styles.hourTextOn]}>
                  {iso === today ? "Today" : d.toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short" })}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      )}
      <Button label="Done" onPress={onClose} testID="days-off-done" />
    </Sheet>
  );
}

export function ImportResultSheet({ result, onClose }: { result: { added: any[]; updated: any[]; skipped: any[] } | null; onClose: () => void }) {
  const styles = useStyles();
  const unknown = [...(result?.added ?? []), ...(result?.updated ?? [])].filter((r) => r.unknown?.length);
  return (
    <Sheet visible={!!result} onClose={onClose} title="Import finished"
      sub={`${result?.added.length ?? 0} added · ${result?.updated.length ?? 0} updated · ${result?.skipped.length ?? 0} skipped`} testID="participants-import-result">
      <ScrollView style={{ maxHeight: 320 }} contentContainerStyle={{ gap: 6 }}>
        {unknown.map((r) => (
          <Text key={`u${r.row}`} style={styles.sub}>Row {r.row} ({r.name}): couldn&apos;t find Support Worker {r.unknown.join(", ")}</Text>
        ))}
        {(result?.skipped ?? []).map((r) => (
          <Text key={`s${r.row}`} style={styles.sub}>Row {r.row}: {r.reason}</Text>
        ))}
      </ScrollView>
      <Button label="Done" onPress={onClose} testID="participants-import-done" />
    </Sheet>
  );
}

export function AddParticipantSheet({ visible, onClose, onDone }: { visible: boolean; onClose: () => void; onDone: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      const p = await api<any>("/participants", { method: "POST", body: { name } });
      toast(`${p.name} added`, "success");
      setName("");
      onDone();
      onClose();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Sheet visible={visible} onClose={onClose} title="Add participant" sub="Use the same name you'll enter on case notes so their history links up." testID="add-participant-sheet">
      <TextInput value={name} onChangeText={setName} placeholder="Participant's full name" placeholderTextColor={colors.muted}
        style={styles.search} autoFocus testID="add-participant-name" />
      <Button label="Add participant" icon="person-add-outline" loading={saving} disabled={name.trim().length < 2} onPress={save} testID="add-participant-save" />
      <Button label="Cancel" variant="ghost" onPress={onClose} testID="add-participant-cancel" />
    </Sheet>
  );
}

export function AssignSheet({ participant, onClose, onDone }: { participant: any | null; onClose: () => void; onDone: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [picked, setPicked] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const q = useQuery<any[]>({ queryKey: ["users"], queryFn: () => api("/users"), enabled: !!participant });
  useEffect(() => {
    setPicked((participant?.assigned ?? []).map((a: any) => a.user_id));
    setSearch("");
  }, [participant]);
  const workers = (q.data ?? []).filter((u) => u.user_type === "support_worker" && u.name?.toLowerCase().includes(search.trim().toLowerCase()));
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const save = async () => {
    setSaving(true);
    try {
      await api(`/participants/${participant.participant_id}/assign`, { method: "PUT", body: { user_ids: picked } });
      toast(`Support Workers updated for ${participant.name}`, "success");
      onDone();
      onClose();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Sheet visible={!!participant} onClose={onClose} title={`Assign Support Workers`}
      sub={`Only ticked Support Workers can see ${participant?.name ?? ""} and their Support Worker case notes.`} testID="assign-sheet">
      <TextInput value={search} onChangeText={setSearch} placeholder="Search Support Workers" placeholderTextColor={colors.muted}
        style={styles.search} testID="assign-search" />
      {q.isLoading ? <Loading /> : (
        <FlatList
          data={workers}
          keyExtractor={(u) => u.user_id}
          style={{ maxHeight: 340 }}
          keyboardShouldPersistTaps="handled"
          ListEmptyComponent={<Text style={styles.sub}>No Support Workers found.</Text>}
          renderItem={({ item }) => {
            const on = picked.includes(item.user_id);
            return (
              <Pressable onPress={() => toggle(item.user_id)} style={styles.row} testID={`assign-user-${item.user_id}`}
                accessibilityRole="checkbox" accessibilityState={{ checked: on }}>
                <Avatar name={item.name} picture={item.picture} size={36} />
                <Text style={[styles.name, { flex: 1 }]}>{item.name}</Text>
                <Ionicons name={on ? "checkbox" : "square-outline"} size={24} color={on ? colors.brandPrimary : colors.muted} />
              </Pressable>
            );
          }}
        />
      )}
      <Button label={`Save (${picked.length} assigned)`} icon="checkmark-outline" loading={saving} onPress={save} testID="assign-save" />
      <Button label="Cancel" variant="ghost" onPress={onClose} testID="assign-cancel" />
    </Sheet>
  );
}

export function CaseFormsSheet({ participant, worker, onClose }: { participant: string | null; worker?: boolean; onClose: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [opening, setOpening] = useState<string | null>(null);
  const pq = useQuery<any>({ queryKey: ["caseload-pending"], queryFn: () => api("/caseload/pending"), enabled: !!participant && !!worker });
  const pending = worker ? pq.data?.pending : null;
  const start = async (item: any) => {
    if (!worker) {
      onClose();
      openLink(item.url);
      return;
    }
    setOpening(item.url);
    try {
      const r = await api<any>("/caseload/forms/open", { method: "POST", body: { participant, form_id: item.form_id ?? "", url: item.url } });
      onClose();
      openLink(r.url);
    } catch (e: any) {
      toast(e.message, "error");
      pq.refetch();
    } finally {
      setOpening(null);
    }
  };
  const q = useQuery<any[]>({
    queryKey: ["caseload-forms", participant],
    queryFn: () => api(`/caseload/forms?participant=${encodeURIComponent(participant ?? "")}`),
    enabled: !!participant,
  });
  return (
    <Sheet visible={!!participant} onClose={onClose} title="Write a case note" sub={`Choose any Day-to-Day form. Where it says "Details filled in", ${participant ?? ""}'s name and yours are added for you.`} testID="case-forms-sheet">
      {worker && pq.isLoading && <Loading />}
      {!!pending && (
        <View style={styles.pendingBox} testID="case-forms-pending">
          <Text style={styles.name}>Finish your last case note first</Text>
          <Text style={styles.sub}>Your {pending.form_title} for {pending.participant_name} hasn&apos;t been submitted yet. Submit it before starting another.</Text>
          <Button label={`Continue ${pending.form_title}`} icon="create-outline" onPress={() => { onClose(); openLink(pending.url); }} testID="case-forms-continue" />
          <Button label="I've submitted it, check again" variant="ghost" loading={pq.isFetching} onPress={() => pq.refetch()} testID="case-forms-recheck" />
        </View>
      )}
      {q.isLoading ? <Loading /> : q.isError ? (
        <ErrorState message={(q.error as any)?.message ?? "Couldn't load forms"} onRetry={q.refetch} />
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(f) => f.url}
          style={{ maxHeight: 380, opacity: pending ? 0.4 : 1 }}
          renderItem={({ item }) => (
            <Pressable onPress={() => start(item)} disabled={!!pending || !!opening} style={styles.row} testID={`case-form-${item.title}`}>
              <Ionicons name={item.kind === "coordinator" ? "briefcase-outline" : "document-text-outline"} size={22} color={colors.brandPrimary} />
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.title}</Text>
                {item.prefilled && <Text style={styles.sub}>Details filled in</Text>}
              </View>
              <Ionicons name={opening === item.url ? "hourglass-outline" : "open-outline"} size={18} color={colors.muted} />
            </Pressable>
          )}
        />
      )}
      <Button label="Cancel" variant="ghost" onPress={onClose} testID="case-forms-cancel" />
    </Sheet>
  );
}

const useStyles = makeStyles((c) => ({
  scrim: { flex: 1, backgroundColor: c.scrim },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, gap: 10 },
  title: { fontSize: 19, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted, lineHeight: 18 },
  search: { minHeight: 44, borderRadius: 12, backgroundColor: c.surfaceSecondary, paddingHorizontal: 14, fontSize: 15, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", gap: 12, minHeight: 52, paddingVertical: 4 },
  name: { fontSize: 15, fontWeight: "600", color: c.onSurface },
  introHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  nudge: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 36, paddingHorizontal: 12, borderRadius: 18, backgroundColor: c.brandTertiary },
  nudgeText: { fontSize: 13, fontWeight: "700", color: c.brandPrimary },
  pendingBox: { backgroundColor: c.warningSoft, borderRadius: 12, padding: 12, gap: 6 },
  hours: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  hour: { minHeight: 44, minWidth: 96, paddingHorizontal: 14, borderRadius: 22, alignItems: "center", justifyContent: "center", backgroundColor: c.surfaceSecondary },
  hourOn: { backgroundColor: c.brandPrimary },
  hourText: { fontSize: 14, fontWeight: "600", color: c.onSurface },
  hourTextOn: { color: c.onBrandPrimary },
  introBody: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
}));
