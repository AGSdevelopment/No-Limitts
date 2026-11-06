// Shift sheets shared by Rostering: shift detail (plan goals), clock reason, approve clock times, new shift.
import { useEffect, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/src/api";
import { Text, TextInput } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Sheet } from "@/src/components/participant-sheets";
import { Button, Chip, Field, Loading, isoToDmy } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export const REASONS = ["Started late so finished late", "Held up in traffic", "Prior shift ran over", "Unavoidable delay"];
export const $ = (n: number) => `$${(n ?? 0).toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const when = (s: any) => `${isoToDmy(s.date)} · ${s.start}–${s.end}`;
export const STATUS: Record<string, string> = {
  pending_acceptance: "Needs your acceptance", accepted: "Accepted", in_progress: "Clocked in",
  awaiting_approval: "Clock times awaiting approval", completed: "Completed", cancelled: "Cancelled", declined: "Declined",
};
const PLAN = [["goals", "Goals"], ["support_needs", "Needs"], ["communication", "Preferences & communication"], ["health_alerts", "Health alerts"]];

export function ShiftDetailSheet({ shiftId, onClose }: { shiftId: string | null; onClose: () => void }) {
  const styles = useStyles();
  const q = useQuery<any>({ queryKey: ["shift", shiftId], queryFn: () => api(`/shifts/${shiftId}`), enabled: !!shiftId });
  const s = q.data;
  return (
    <Sheet visible={!!shiftId} onClose={onClose} title={s?.participant_name ?? "Shift"} sub={s ? `${when(s)} · ${s.worker_name}` : ""} testID="shift-detail-sheet">
      {!s ? <Loading /> : (
        <ScrollView style={{ maxHeight: 460 }} contentContainerStyle={{ gap: 8 }}>
          {!!s.funding_type && <Text style={styles.meta}>Funding: {s.funding_type}{s.est_cost != null ? ` · est. ${$(s.est_cost)}` : ""}</Text>}
          {!!s.notes && <Text style={styles.body}>{s.notes}</Text>}
          <Text style={styles.label}>Support Plan summary</Text>
          {PLAN.map(([k, label]) => (
            <View key={k} style={{ gap: 2 }}>
              <Text style={styles.small}>{label}</Text>
              <Text style={styles.body} testID={`shift-plan-${k}`}>{s.plan?.[k] || "Not added yet — ask the Service Coordinator."}</Text>
            </View>
          ))}
          <Button label="Close" variant="ghost" onPress={onClose} />
        </ScrollView>
      )}
    </Sheet>
  );
}

export function ReasonSheet({ open, kind, onClose, onSubmit, busy }: {
  open: boolean; kind: "in" | "out"; onClose: () => void; onSubmit: (reason: string, detail: string) => void; busy?: boolean;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [reason, setReason] = useState("");
  const [detail, setDetail] = useState("");
  useEffect(() => {
    if (open) { setReason(""); setDetail(""); }
  }, [open, kind]);
  const needsText = reason === "Unavoidable delay";
  return (
    <Sheet visible={open} onClose={onClose} title={`Why are you clocking ${kind} outside the shift time?`}
      sub="You're more than 5 minutes from the rostered time. Rosters will review and approve the times." testID="clock-reason-sheet">
      {REASONS.map((r) => (
        <Pressable key={r} onPress={() => setReason(r)} style={[styles.reason, reason === r && styles.reasonOn]} accessibilityRole="radio"
          accessibilityState={{ selected: reason === r }} testID={`clock-reason-${REASONS.indexOf(r)}`}>
          <Text style={[styles.body, reason === r && { fontWeight: "700" }]}>{r}</Text>
        </Pressable>
      ))}
      {needsText && (
        <TextInput value={detail} onChangeText={setDetail} placeholder="Tell us what happened" placeholderTextColor={colors.muted}
          multiline maxLength={500} style={styles.input} testID="clock-reason-detail" />
      )}
      <Button label={`Clock ${kind}`} loading={busy} disabled={!reason || (needsText && detail.trim().length < 3) || busy}
        onPress={() => onSubmit(reason, detail)} testID="clock-reason-submit" />
      <Button label="Cancel" variant="ghost" onPress={onClose} />
    </Sheet>
  );
}

export function ApproveSheet({ shift, onClose, onDone }: { shift: any; onClose: () => void; onDone: () => void }) {
  const styles = useStyles();
  const toast = useToast();
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const s = shift;
  const save = async () => {
    setBusy(true);
    try {
      const r = await api<any>(`/shifts/${s.shift_id}/approve`, { method: "POST", body: { start: start || s.clock_in?.time, end: end || s.clock_out?.time, comment } });
      toast(r.over_budget ? "Approved, but this shift is over the remaining budget" : "Clock times approved", r.over_budget ? "info" : "success");
      setStart(""); setEnd(""); setComment("");
      onDone();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet visible={!!s} onClose={onClose} title={s ? `${s.worker_name} · ${s.participant_name}` : ""} sub={s ? `Rostered ${when(s)}` : ""} testID="approve-sheet">
      {s && (
        <ScrollView style={{ maxHeight: 480 }} contentContainerStyle={{ gap: 8 }} keyboardShouldPersistTaps="handled">
          <Text style={styles.body}>Clocked in {s.clock_in?.time ?? "-"}{s.clock_in?.reason ? ` · ${s.clock_in.reason}` : ""}</Text>
          {!!s.clock_in?.detail && <Text style={styles.meta}>“{s.clock_in.detail}”</Text>}
          <Text style={styles.body}>Clocked out {s.clock_out?.time ?? "-"}{s.clock_out?.reason ? ` · ${s.clock_out.reason}` : ""}</Text>
          {!!s.clock_out?.detail && <Text style={styles.meta}>“{s.clock_out.detail}”</Text>}
          <View style={{ flexDirection: "row", gap: 8 }}>
            <View style={{ flex: 1 }}><Field label="Approved start" value={start} onChangeText={setStart} placeholder={s.clock_in?.time} testID="approve-start" /></View>
            <View style={{ flex: 1 }}><Field label="Approved finish" value={end} onChangeText={setEnd} placeholder={s.clock_out?.time} testID="approve-end" /></View>
          </View>
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            <Chip label="Use rostered times" selected={start === s.start && end === s.end} onPress={() => { setStart(s.start); setEnd(s.end); }} testID="approve-use-rostered" />
            <Chip label="Use clock times" selected={!start && !end} onPress={() => { setStart(""); setEnd(""); }} testID="approve-use-clock" />
          </View>
          <Field label="Comment (optional)" value={comment} onChangeText={setComment} testID="approve-comment" />
          <Button label="Approve times" icon="checkmark" loading={busy} disabled={busy} onPress={save} testID="approve-save" />
          <Button label="Cancel" variant="ghost" onPress={onClose} />
        </ScrollView>
      )}
    </Sheet>
  );
}

export function NewShiftSheet({ open, onClose, onDone, prefill }: {
  open: boolean; onClose: () => void; onDone: () => void; prefill?: any;
}) {
  const styles = useStyles();
  const toast = useToast();
  const q = useQuery<any[]>({ queryKey: ["pm-options"], queryFn: () => api("/pm/options"), enabled: open });
  const [pid, setPid] = useState("");
  const [fid, setFid] = useState("");
  const [wid, setWid] = useState("");
  const [form, setForm] = useState({ date: "", start: "", end: "", notes: "" });
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open || !prefill) return;
    setPid(prefill.participant_id);
    setFid(prefill.funding_id);
    setWid("");
    setForm({ date: isoToDmy(prefill.date), start: prefill.start, end: prefill.end, notes: prefill.notes ?? "" });
  }, [open, prefill]);
  const p = q.data?.find((x) => x.participant_id === pid);
  const save = async () => {
    setBusy(true);
    try {
      const s = await api<any>("/shifts", { method: "POST", body: { participant_id: pid, funding_id: fid, worker_id: wid, ...form, replaces: prefill?.shift_id ?? "" } });
      toast(s.status === "accepted" ? "Shift rostered (auto-accepted, 2+ weeks away)" : "Shift rostered. The worker needs to accept it.", "success");
      setForm({ date: "", start: "", end: "", notes: "" });
      onDone();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet visible={open} onClose={() => !busy && onClose()} title={prefill ? "Re-roster shift" : "New shift"}
      sub={prefill ? `${prefill.worker_name} declined: “${prefill.decline_reason ?? ""}”. Pick someone else from the Support Team.` : "Only approved Support Team members and funded lines can be rostered."} testID="new-shift-sheet">
      {q.isLoading ? <Loading /> : (
        <ScrollView style={{ maxHeight: 520 }} contentContainerStyle={{ gap: 8 }} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>Participant</Text>
          <View style={styles.chips}>
            {(q.data ?? []).filter((x) => x.funding.length).map((x) => (
              <Chip key={x.participant_id} label={x.name} selected={pid === x.participant_id}
                onPress={() => { setPid(x.participant_id); setFid(x.funding[0]?.funding_id ?? ""); setWid(""); }} testID={`new-shift-p-${x.participant_id}`} />
            ))}
          </View>
          {!q.data?.some((x) => x.funding.length) && <Text style={styles.meta}>No participants have current funding yet.</Text>}
          {p && (
            <>
              <Text style={styles.label}>Funding</Text>
              {p.funding.map((f: any) => (
                <Pressable key={f.funding_id} onPress={() => setFid(f.funding_id)} style={[styles.reason, fid === f.funding_id && styles.reasonOn]}
                  testID={`new-shift-f-${f.funding_id}`}>
                  <Text style={[styles.body, { fontWeight: "700" }]}>{f.management_type} · {f.unit_type} @ {$(f.unit_rate)}</Text>
                  <Text style={styles.meta}>{$(f.available)} available · {isoToDmy(f.start_date)} to {isoToDmy(f.end_date)}</Text>
                </Pressable>
              ))}
              <Text style={styles.label}>Support Team member</Text>
              <View style={styles.chips}>
                {p.team.filter((w: any) => w.user_id !== prefill?.worker_id).map((w: any) => (
                  <Chip key={w.user_id} label={w.name} selected={wid === w.user_id} onPress={() => setWid(w.user_id)} testID={`new-shift-w-${w.user_id}`} />
                ))}
              </View>
              {!p.team.filter((w: any) => w.user_id !== prefill?.worker_id).length && (
                <Text style={styles.meta}>{prefill ? "No one else is on this participant's Support Team yet. Tag staff in Team Directory." : "No approved Support Team yet. Tag staff in Team Directory."}</Text>
              )}
            </>
          )}
          <Field label="Date (DD-MM-YYYY)" value={form.date} onChangeText={(v) => setForm({ ...form, date: v })} placeholder="DD-MM-YYYY" testID="new-shift-date" />
          <View style={{ flexDirection: "row", gap: 8 }}>
            <View style={{ flex: 1 }}><Field label="Start (24hr)" value={form.start} onChangeText={(v) => setForm({ ...form, start: v })} placeholder="09:00" testID="new-shift-start" /></View>
            <View style={{ flex: 1 }}><Field label="Finish (24hr)" value={form.end} onChangeText={(v) => setForm({ ...form, end: v })} placeholder="13:00" testID="new-shift-end" /></View>
          </View>
          <Field label="Notes for the worker (optional)" value={form.notes} onChangeText={(v) => setForm({ ...form, notes: v })} testID="new-shift-notes" />
          <Button label="Roster shift" icon="add" loading={busy} disabled={busy || !pid || !fid || !wid || !form.date || !form.start || !form.end}
            onPress={save} testID="new-shift-save" />
          <Button label="Cancel" variant="ghost" onPress={onClose} />
        </ScrollView>
      )}
    </Sheet>
  );
}

export function DeclineSheet({ shift, onClose, onDone }: { shift: any; onClose: () => void; onDone: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (shift) setText(""); }, [shift]);
  const save = async () => {
    setBusy(true);
    try {
      await api(`/shifts/${shift.shift_id}/decline`, { method: "POST", body: { reason: text } });
      toast("Shift declined. Rosters have been told.", "success");
      onDone();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet visible={!!shift} onClose={() => !busy && onClose()} title="Decline this shift?" sub={shift ? `${shift.participant_name} · ${when(shift)}` : ""} testID="decline-sheet">
      <TextInput value={text} onChangeText={setText} placeholder="Why can't you do this shift?" placeholderTextColor={colors.muted}
        multiline maxLength={300} style={styles.input} testID="decline-reason" />
      <Button label="Decline shift" variant="danger" loading={busy} disabled={busy || text.trim().length < 3} onPress={save} testID="decline-submit" />
      <Button label="Keep shift" variant="ghost" onPress={onClose} />
    </Sheet>
  );
}

export function CaseNoteGate({ shift, onClose, onWrite, onRetry, busy }: {
  shift: any; onClose: () => void; onWrite: () => void; onRetry: () => void; busy?: boolean;
}) {
  return (
    <Sheet visible={!!shift} onClose={onClose} title="Complete your case note first"
      sub={shift ? `Submit today's case note for ${shift.participant_name} before you clock out.` : ""} testID="case-note-gate">
      <Button label="Write case note" icon="create-outline" onPress={onWrite} testID="case-note-gate-write" />
      <Button label="I've submitted it, clock out" icon="log-out-outline" variant="secondary" loading={busy} onPress={onRetry} testID="case-note-gate-retry" />
      <Button label="Not now" variant="ghost" onPress={onClose} />
    </Sheet>
  );
}

const useStyles = makeStyles((c) => ({
  body: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
  small: { fontSize: 12, fontWeight: "700", color: c.brandPrimary },
  label: { fontSize: 12, fontWeight: "700", color: c.muted, textTransform: "uppercase", marginTop: 4 },
  chips: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  reason: { minHeight: 48, justifyContent: "center", borderRadius: 12, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: c.surfaceSecondary },
  reasonOn: { borderWidth: 2, borderColor: c.brandPrimary, backgroundColor: c.brandTertiary },
  input: { minHeight: 72, borderRadius: 12, padding: 12, fontSize: 15, color: c.onSurface, backgroundColor: c.surfaceSecondary, textAlignVertical: "top" },
}));
