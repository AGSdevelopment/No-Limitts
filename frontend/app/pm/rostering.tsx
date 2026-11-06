// Rostering: Rosters roster shifts, approve clock exceptions and download the report; Support Workers accept and clock in / out.
import { useRef, useState } from "react";
import { FlatList, Pressable, RefreshControl, ScrollView, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ApiError, API_URL, api, getApiToken, openLink } from "@/src/api";
import { Text } from "@/src/components/text";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, Chip, EmptyState, Field, Ionicons, Loading, Pill, dmyToIso } from "@/src/components/ui";
import { ApproveSheet, CaseNoteGate, DeclineSheet, NewShiftSheet, ReasonSheet, STATUS, ShiftDetailSheet, when } from "@/src/components/shift-sheets";
import { CaseFormsSheet } from "@/src/components/participant-sheets";
import { WeekRoster } from "@/src/components/week-roster";
import { OfferLink, OffersPanel, SwapSheet, SwapStatus } from "@/src/components/shift-market";
import { Fix, useClockLocation } from "@/src/components/clock-location";
import { makeStyles, useTheme } from "@/src/theme";

type Tab = "roster" | "week" | "approvals" | "offers" | "report" | "mine";

// Clock in opens 2 hours before the shift (Perth time, UTC+8 with no daylight saving) until it finishes
function clockable(s: any) {
  const start = new Date(`${s.date}T${s.start}:00+08:00`).getTime();
  let end = new Date(`${s.date}T${s.end}:00+08:00`).getTime();
  if (end <= start) end += 86400000;
  const now = Date.now();
  return now >= start - 2 * 3600000 && now <= end;
}

// Workers can decline shifts starting within the next 14 days (and not yet started)
function declinable(s: any) {
  const start = new Date(`${s.date}T${s.start}:00+08:00`).getTime();
  const now = Date.now();
  return ["pending_acceptance", "accepted"].includes(s.status) && start > now && start <= now + 14 * 86400000;
}

export default function Rostering() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const acc = useQuery<any>({ queryKey: ["pm-access"], queryFn: () => api("/pm/access") });
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab | null>(null);
  const rosters = !!acc.data?.rosters;
  const active: Tab = tab ?? (rosters ? "roster" : "mine");
  const mine = active === "mine";
  const q = useQuery<any[]>({
    queryKey: ["shifts", active], enabled: !!acc.data && active !== "report",
    queryFn: () => api(active === "approvals" ? "/shifts?status=awaiting_approval" : "/shifts"),
  });
  const [detail, setDetail] = useState<string | null>(null);
  const [approve, setApprove] = useState<any>(null);
  const [adding, setAdding] = useState(false);
  const [reason, setReason] = useState<{ s: any; kind: "in" | "out" } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [range, setRange] = useState({ from: "", to: "" });
  const [declining, setDeclining] = useState<any>(null);
  const [gate, setGate] = useState<any>(null);
  const [notesFor, setNotesFor] = useState<string | null>(null);
  const [reroster, setReroster] = useState<any>(null);
  const [swapping, setSwapping] = useState<any>(null);
  const { getFix, sheet: locationSheet } = useClockLocation();
  const fixRef = useRef<{ id: string; fix: Fix | null } | null>(null);

  if (acc.isLoading) return <Loading />;
  const shifts = (q.data ?? []).filter((s) => (mine && rosters ? s.worker_id === user?.user_id : true))
    .filter((s) => s.status !== "cancelled");

  const act = async (s: any, path: string, body?: any) => {
    setBusy(s.shift_id);
    try {
      let payload = body ?? {};
      if (path === "clock-in") {
        // Read the location once per clock-in attempt; the reason retry reuses it so no second prompt opens over the reason sheet
        if (!body?.reason || fixRef.current?.id !== s.shift_id) fixRef.current = { id: s.shift_id, fix: await getFix() };
        const f = fixRef.current.fix;
        if (f) payload = { ...payload, lat: f.lat, lng: f.lng, accuracy: f.accuracy };
      }
      const r = await api<any>(`/shifts/${s.shift_id}/${path}`, { method: "POST", body: payload });
      setReason(null);
      setGate(null);
      if (r.clock_in?.location?.flagged) toast(`Clocked in. ${r.clock_in.location.note}, so Rosters will review your times.`, "info");
      else toast(path === "accept" ? "Shift accepted" : r.status === "awaiting_approval" ? "Clocked out. Rosters will approve your times." : path === "clock-in" ? "Clocked in" : "Clocked out", "success");
      q.refetch();
    } catch (e: any) {
      if (e instanceof ApiError && e.message === "outside_window") setReason({ s, kind: path === "clock-in" ? "in" : "out" });
      else if (e instanceof ApiError && e.message === "case_note_required") { setReason(null); setGate({ s, body }); }
      else toast(e.message, "error");
    } finally {
      setBusy(null);
    }
  };
  const cancel = async (s: any) => {
    try {
      await api(`/shifts/${s.shift_id}`, { method: "DELETE" });
      toast("Shift cancelled", "success");
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const report = () => {
    const a = dmyToIso(range.from), b = dmyToIso(range.to);
    if (!a || !b) return toast("Enter both dates as DD-MM-YYYY", "error");
    if (a > b) return toast("The start date must be before the end date", "error");
    if ((new Date(b).getTime() - new Date(a).getTime()) / 86400000 + 1 > 90) return toast("Choose 1 to 90 days", "error");
    openLink(`${API_URL}/roster/report?date_from=${a}&date_to=${b}&token=${encodeURIComponent(getApiToken() ?? "")}`);
  };

  const tabs = (
    <View style={styles.chips}>
      {rosters && <Chip label="Roster" selected={active === "roster"} onPress={() => setTab("roster")} testID="roster-tab-roster" />}
      {rosters && <Chip label="Week" selected={active === "week"} onPress={() => setTab("week")} testID="roster-tab-week" />}
      {rosters && <Chip label={`Approvals${acc.data?.awaiting_approval ? ` (${acc.data.awaiting_approval})` : ""}`} selected={active === "approvals"} onPress={() => setTab("approvals")} testID="roster-tab-approvals" />}
      {(rosters || acc.data?.finance) && <Chip label="Report" selected={active === "report"} onPress={() => setTab("report")} testID="roster-tab-report" />}
      {rosters && acc.data?.worker && <Chip label="My shifts" selected={mine} onPress={() => setTab("mine")} testID="roster-tab-mine" />}
      {!rosters && <Chip label="My shifts" selected={mine} onPress={() => setTab("mine")} testID="roster-tab-mine" />}
      <Chip label="Swaps & open shifts" selected={active === "offers"} onPress={() => setTab("offers")} testID="roster-tab-offers" />
    </View>
  );

  if (active === "offers") {
    return (
      <ScrollView style={styles.root} contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }} testID="roster-offers">
        {tabs}
        <OffersPanel onChanged={() => { q.refetch(); acc.refetch(); }} />
      </ScrollView>
    );
  }

  if (active === "week") {
    return (
      <>
        <ScrollView style={styles.root} contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }} testID="roster-week">
          {tabs}
          <WeekRoster onOpen={setDetail} />
        </ScrollView>
        <ShiftDetailSheet shiftId={detail} onClose={() => setDetail(null)} />
      </>
    );
  }

  if (active === "report") {
    return (
      <View style={[styles.root, { padding: 16, gap: 12 }]} testID="roster-report">
        {tabs}
        <Text style={styles.title}>Clock in/out exceptions report</Text>
        <Text style={styles.meta}>Excel summary of clock in/out incidents that needed approval and the unbudgeted minutes and hours, for 1 to 90 days.</Text>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <View style={{ flex: 1 }}><Field label="From" value={range.from} onChangeText={(v) => setRange({ ...range, from: v })} placeholder="DD-MM-YYYY" testID="report-from" /></View>
          <View style={{ flex: 1 }}><Field label="To" value={range.to} onChangeText={(v) => setRange({ ...range, to: v })} placeholder="DD-MM-YYYY" testID="report-to" /></View>
        </View>
        <Button label="Download Excel report" icon="download-outline" onPress={report} testID="report-download" />
      </View>
    );
  }

  return (
    <>
      <FlatList
        style={styles.root}
        testID="rostering-screen"
        data={shifts}
        keyExtractor={(s) => s.shift_id}
        contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => { q.refetch(); acc.refetch(); }} tintColor={colors.brandPrimary} />}
        ListHeaderComponent={
          <View style={{ gap: 10, marginBottom: 4 }}>
            {tabs}
            {active === "roster" && <Button label="New shift" icon="add" onPress={() => setAdding(true)} testID="roster-new-shift" />}
            {mine && <Text style={styles.meta}>Shifts within 2 weeks need accepting. Clock in and out within 5 minutes of the rostered times.</Text>}
          </View>
        }
        ListEmptyComponent={q.isLoading ? <Loading /> : (
          <EmptyState icon="calendar-outline" title={active === "approvals" ? "Nothing to approve" : "No shifts"}
            subtitle={active === "approvals" ? "Clock times outside the 5-minute window show here." : mine ? "Your rostered shifts will show here." : "Tap New shift to roster someone."} />
        )}
        renderItem={({ item: s }) => (
          <Pressable onPress={() => setDetail(s.shift_id)} style={styles.card} testID={`shift-${s.shift_id}`}>
            <View style={styles.row}>
              <Text style={[styles.title, { flex: 1 }]}>{mine ? s.participant_name : `${s.worker_name} → ${s.participant_name}`}</Text>
              {!!s.funding_type && !mine && <Pill label={s.funding_type} tone="accent" />}
            </View>
            <Text style={styles.body}>{when(s)}</Text>
            <Text style={[styles.meta, s.status === "pending_acceptance" && { color: colors.warningText, fontWeight: "700" }]}>
              {s.status === "pending_acceptance" && !mine ? "Waiting for the worker to accept" : STATUS[s.status] ?? s.status}{s.auto_accepted ? " (auto)" : ""}
              {s.clock_in ? ` · in ${s.clock_in.time}` : ""}{s.clock_out ? ` · out ${s.clock_out.time}` : ""}
              {s.approved_minutes != null ? ` · ${s.approved_minutes} min approved` : ""}
            </Text>
            {s.clock_in?.location?.flagged && !mine && <Text style={[styles.meta, { color: colors.warningText, fontWeight: "700" }]}>📍 {s.clock_in.location.note}</Text>}
            {mine && s.status === "pending_acceptance" && (
              <Button label="Accept shift" icon="checkmark" loading={busy === s.shift_id} onPress={() => act(s, "accept")} testID={`shift-accept-${s.shift_id}`} />
            )}
            {mine && s.status === "accepted" && clockable(s) && (
              <Button label="Clock in" icon="log-in-outline" loading={busy === s.shift_id} onPress={() => act(s, "clock-in")} testID={`shift-clockin-${s.shift_id}`} />
            )}
            {mine && s.status === "in_progress" && (
              <Button label="Clock out" icon="log-out-outline" loading={busy === s.shift_id} onPress={() => act(s, "clock-out")} testID={`shift-clockout-${s.shift_id}`} />
            )}
            <SwapStatus s={s} />
            {mine && ["pending_acceptance", "accepted"].includes(s.status) && !["pending_teammate", "pending_rosters"].includes(s.swap?.status)
              && new Date(`${s.date}T${s.start}:00+08:00`).getTime() > Date.now() && (
              <OfferLink onPress={() => setSwapping(s)} testID={`shift-swap-${s.shift_id}`} />
            )}
            {active === "roster" && s.status === "declined" && !s.rerostered && !s.open && (
              <Button label="Post to open shift board" icon="megaphone-outline" variant="secondary" onPress={async () => {
                try {
                  const r = await api<any>(`/shifts/${s.shift_id}/open`, { method: "POST" });
                  toast(`Posted. ${r.notified} Support Team member${r.notified === 1 ? "" : "s"} told.`, "success");
                  q.refetch();
                } catch (e: any) {
                  toast(e.message, "error");
                }
              }} testID={`shift-open-${s.shift_id}`} />
            )}
            {s.open && <Text style={[styles.meta, { color: colors.brandPrimary, fontWeight: "700" }]}>On the open shift board</Text>}
            {mine && declinable(s) && (
              <Pressable onPress={() => setDeclining(s)} style={styles.link} testID={`shift-decline-${s.shift_id}`}>
                <Ionicons name="close-circle-outline" size={16} color={colors.errorText} />
                <Text style={[styles.meta, { color: colors.errorText, fontWeight: "700" }]}>Can&apos;t do it? Decline</Text>
              </Pressable>
            )}
            {s.status === "declined" && (
              <Text style={[styles.meta, { color: colors.errorText }]}>{s.rerostered ? "Re-rostered · " : ""}Reason: “{s.decline_reason ?? ""}”</Text>
            )}
            {active === "roster" && s.status === "declined" && !s.rerostered && (
              <Button label="Re-roster" icon="repeat-outline" onPress={() => setReroster(s)} testID={`shift-reroster-${s.shift_id}`} />
            )}
            {active === "approvals" && (
              <Button label="Review times" icon="time-outline" onPress={() => setApprove(s)} testID={`shift-review-${s.shift_id}`} />
            )}
            {active === "roster" && ["pending_acceptance", "accepted"].includes(s.status) && (
              <Pressable onPress={() => cancel(s)} style={styles.link} testID={`shift-cancel-${s.shift_id}`}>
                <Ionicons name="close-circle-outline" size={16} color={colors.errorText} />
                <Text style={[styles.meta, { color: colors.errorText, fontWeight: "700" }]}>Cancel shift</Text>
              </Pressable>
            )}
          </Pressable>
        )}
      />
      <ShiftDetailSheet shiftId={detail} onClose={() => setDetail(null)} />
      <ApproveSheet shift={approve} onClose={() => setApprove(null)} onDone={() => { setApprove(null); q.refetch(); acc.refetch(); }} />
      <NewShiftSheet open={adding || !!reroster} prefill={reroster} onClose={() => { setAdding(false); setReroster(null); }}
        onDone={() => { setAdding(false); setReroster(null); q.refetch(); }} />
      <DeclineSheet shift={declining} onClose={() => setDeclining(null)} onDone={() => { setDeclining(null); q.refetch(); }} />
      <SwapSheet shift={swapping} onClose={() => setSwapping(null)} onDone={() => { setSwapping(null); q.refetch(); }} />
      <CaseNoteGate shift={gate?.s} busy={!!busy} onClose={() => setGate(null)}
        onWrite={() => { setNotesFor(gate.s.participant_name); }}
        onRetry={() => gate && act(gate.s, "clock-out", gate.body)} />
      <CaseFormsSheet participant={notesFor} worker onClose={() => setNotesFor(null)} />
      {locationSheet}
      <ReasonSheet open={!!reason} kind={reason?.kind ?? "in"} busy={!!busy} onClose={() => setReason(null)}
        onSubmit={(r, d) => reason && act(reason.s, reason.kind === "in" ? "clock-in" : "clock-out", { reason: r, detail: r === "Unavoidable delay" ? d : "" })} />
    </>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  chips: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  card: { backgroundColor: c.surface, borderRadius: 14, padding: 14, gap: 6 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  body: { fontSize: 14, color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
  link: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, alignSelf: "flex-start" },
}));
