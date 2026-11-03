// Service & Support Coordinators: their participants and recent case notes (from the Jotform Coordinator Case Note Form).
import { useState } from "react";
import { FlatList, Pressable, RefreshControl, View } from "react-native";
import { Text, TextInput } from "@/src/components/text";
import { useQuery } from "@tanstack/react-query";
import { router } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders, getApiToken, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { StaffEmailSheet } from "@/src/components/staff-email-sheet";
import { HandoverPhotos } from "@/src/components/handover-photos";
import { AddParticipantSheet, AssignSheet, CaseFormsSheet, ConfirmSheet, DaysOffSheet, HourSheet, ImportResultSheet, IntroSheet, NudgeButton, hourLabel } from "@/src/components/participant-sheets";
import * as DocumentPicker from "expo-document-picker";
import { uploadForm } from "@/src/utils/upload";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, EmptyState, ErrorState, Ionicons, Loading, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const CASE_NOTE_FORM = "https://nolimitts.jotform.com/262772090420048";

export default function Caseload() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const [refreshing, setRefreshing] = useState(false);
  const { user } = useAuth();
  const allowed = user?.role === "admin" || ["support_coordinator", "hr", "support_worker"].includes(user?.user_type ?? "");
  const q = useQuery<any>({ queryKey: ["caseload"], queryFn: () => api("/caseload"), enabled: allowed });
  const [open, setOpen] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const toast = useToast();
  const [summaries, setSummaries] = useState<Record<string, string>>({});
  const [summarising, setSummarising] = useState<string | null>(null);
  const [emailing, setEmailing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [assigning, setAssigning] = useState<any>(null);
  const [writing, setWriting] = useState<string | null>(null);
  const [removing, setRemoving] = useState<any>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [acking, setAcking] = useState<string | null>(null);
  const [introDone, setIntroDone] = useState<string[]>([]);
  const [unassignedOnly, setUnassignedOnly] = useState(false);
  const [pickingHour, setPickingHour] = useState(false);
  const [daysOffOpen, setDaysOffOpen] = useState(false);
  const settings = useQuery<any>({ queryKey: ["caseload-settings"], queryFn: () => api("/caseload/settings"), enabled: allowed && user?.role === "admin" });
  const saveHour = async (hour: number) => {
    try {
      await api("/caseload/settings", { method: "PUT", body: { hour } });
      await settings.refetch();
      toast(`Case note reminders will go out at ${hourLabel(hour)} (Perth time)`, "success");
      setPickingHour(false);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const [emailingReport, setEmailingReport] = useState(false);
  const emailReport = async () => {
    setEmailingReport(true);
    try {
      const r = await api<any>("/caseload/monthly-report/email", { method: "POST" });
      toast(`Report sent to ${r.sent_to}`, "success");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setEmailingReport(false);
    }
  };
  const clearPending = async (startId: string) => {
    try {
      await api(`/caseload/pending/${startId}`, { method: "DELETE" });
      toast("Released. They can start a new case note.", "success");
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const ack = async (item: any) => {
    setAcking(item.handover.id);
    try {
      await api("/caseload/handover/ack", { method: "POST", body: { submission_id: item.handover.id, participant: item.name } });
      await q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setAcking(null);
    }
  };
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState<{ added: any[]; updated: any[]; skipped: any[] } | null>(null);

  const importSheet = async () => {
    const pick = await DocumentPicker.getDocumentAsync({ copyToCacheDirectory: true,
      type: ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv", "text/comma-separated-values", "application/vnd.ms-excel"] });
    const f = pick.canceled ? null : pick.assets?.[0];
    if (!f) return;
    setImporting(true);
    try {
      const res = await uploadForm(`${API_URL}/participants/import`, { headers: authHeaders(), files: { file: { uri: f.uri, name: f.name, mimeType: f.mimeType ?? undefined } } });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Import failed");
      setImported(body);
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setImporting(false);
    }
  };

  const remove = async () => {
    if (removeBusy) return;
    setRemoveBusy(true);
    try {
      await api(`/participants/${removing.participant_id}`, { method: "DELETE" });
      toast(`${removing.name} removed from the list`, "success");
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setRemoveBusy(false);
      setRemoving(null);
    }
  };

  const summarise = async (name: string) => {
    setSummarising(name);
    try {
      const r = await api<any>("/caseload/summary", { method: "POST", body: { name } });
      setSummaries((s) => ({ ...s, [name]: r.summary }));
    } catch (e: any) {
      toast(e.message ?? "Couldn't summarise right now", "error");
    } finally {
      setSummarising(null);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    try {
      await api("/caseload?refresh=true");
      q.refetch();
    } finally {
      setRefreshing(false);
    }
  };

  if (!allowed) return <EmptyState icon="lock-closed-outline" title="Not available" subtitle="The caseload is for Coordinators, HR and Support Workers." />;

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as any)?.message ?? "Couldn't load your caseload"} onRetry={q.refetch} />;
  const worker = !!q.data.worker;
  const people = (q.data.participants ?? []).filter((p: any) => p.name.toLowerCase().includes(search.trim().toLowerCase())
    && (!unassignedOnly || (p.participant_id && !p.assigned.length)));
  const unassignedCount = (q.data.participants ?? []).filter((p: any) => p.participant_id && !p.assigned.length).length;

  return (
    <>
    <FlatList
      style={styles.root}
      testID="caseload-screen"
      data={people}
      keyExtractor={(p) => p.name}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.brandPrimary} />}
      ListHeaderComponent={
        <View style={{ gap: 10 }}>
          {!worker && (
            <Pressable onPress={() => openLink(CASE_NOTE_FORM)} style={styles.newNote} testID="caseload-new-note">
              <Ionicons name="create-outline" size={20} color={colors.onBrandPrimary} />
              <Text style={styles.newNoteText}>Write a case note</Text>
            </Pressable>
          )}
          {q.data.can_manage && (
            <>
              <View style={styles.manageRow}>
                <Button label="Add one" icon="person-add-outline" variant="secondary" onPress={() => setAdding(true)} style={{ flex: 1 }} testID="caseload-add-participant" />
                <Button label={importing ? "Importing…" : "Import sheet"} icon="cloud-upload-outline" variant="secondary" loading={importing}
                  onPress={importSheet} style={{ flex: 1 }} testID="caseload-import" />
              </View>
              <Pressable onPress={() => openLink(`${API_URL}/participants/import-template?token=${encodeURIComponent(getApiToken() ?? "")}`)}
                style={styles.templateLink} testID="caseload-import-template">
                <Ionicons name="download-outline" size={16} color={colors.brandPrimary} />
                <Text style={styles.templateText}>Download the participant spreadsheet template</Text>
              </Pressable>
              <Pressable onPress={() => openLink(`${API_URL}/participants/export?token=${encodeURIComponent(getApiToken() ?? "")}`)}
                style={styles.templateLink} testID="caseload-export">
                <Ionicons name="grid-outline" size={16} color={colors.brandPrimary} />
                <Text style={styles.templateText}>Download assignments spreadsheet (for rostering)</Text>
              </Pressable>
            </>
          )}
          {worker && <Text style={styles.meta}>Participants you&apos;re assigned to. Tap one to write a case note or read their Support Worker notes.</Text>}
          {worker && q.data.streak && (
            <View style={styles.streak} testID="caseload-streak">
              <Ionicons name="flame" size={26} color={q.data.streak.current ? colors.brandPrimary : colors.muted} />
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{q.data.streak.current ? `${q.data.streak.current}-day case note streak` : "Start a case note streak"}</Text>
                <Text style={styles.meta}>
                  {q.data.streak.today_off ? "Today is marked as a day off." : q.data.streak.today_done ? "Today's done. Nice work!" : "Complete today's case notes to keep it going."}
                  {q.data.streak.best > 1 ? ` Best: ${q.data.streak.best} days.` : ""}
                </Text>
                <View style={styles.streakLinks}>
                  <Pressable onPress={() => router.push("/leaderboard?tab=streaks")} style={styles.templateLink} testID="caseload-streak-board">
                    <Ionicons name="trophy-outline" size={16} color={colors.brandPrimary} />
                    <Text style={styles.templateText}>Leaderboard</Text>
                  </Pressable>
                  <Pressable onPress={() => setDaysOffOpen(true)} style={styles.templateLink} testID="caseload-days-off">
                    <Ionicons name="calendar-clear-outline" size={16} color={colors.brandPrimary} />
                    <Text style={styles.templateText}>Days off</Text>
                  </Pressable>
                </View>
              </View>
            </View>
          )}
          {q.data.can_manage && (
            <View style={styles.manageRow}>
              <Button label="Missed notes" icon="calendar-outline" variant="secondary" onPress={() => router.push("/missed-notes")} style={{ flex: 1 }} testID="caseload-missed" />
              {user?.role === "admin" && (
                <Button label={hourLabel(settings.data?.reminder_hour ?? 18)} icon="alarm-outline" variant="secondary"
                  onPress={() => setPickingHour(true)} style={{ flex: 1 }} testID="caseload-reminder-time" />
              )}
            </View>
          )}
          {q.data.can_manage && (
            <View style={styles.reportBox} testID="caseload-monthly-report">
              <View style={styles.aiHead}>
                <Ionicons name="stats-chart-outline" size={16} color={colors.brandPrimary} />
                <Text style={styles.aiTitle}>Monthly case note report</Text>
              </View>
              <Text style={styles.meta}>Emailed to each coordinator on the 1st of every month. You can open last month&apos;s now.</Text>
              <Pressable onPress={() => router.push("/team-certificates")} style={styles.templateLink} testID="caseload-team-certs">
                <Ionicons name="ribbon-outline" size={16} color={colors.brandPrimary} />
                <Text style={styles.templateText}>Team certificates expiring soon</Text>
              </Pressable>
              <View style={styles.manageRow}>
                <Button label="Open PDF" icon="document-text-outline" variant="secondary" style={{ flex: 1 }}
                  onPress={() => openLink(`${API_URL}/caseload/monthly-report/pdf?token=${encodeURIComponent(getApiToken() ?? "")}`)}
                  testID="caseload-monthly-pdf" />
                <Button label="Email to me" icon="mail-outline" variant="secondary" style={{ flex: 1 }} loading={emailingReport}
                  onPress={emailReport} testID="caseload-monthly-email" />
              </View>
            </View>
          )}
          <TextInput value={search} onChangeText={setSearch} placeholder="Search participants" placeholderTextColor={colors.muted}
            style={styles.search} testID="caseload-search" />
          {q.data.can_manage && (
            <View style={styles.chips}>
              {[{ on: false, label: "All participants" }, { on: true, label: `No Support Worker (${unassignedCount})` }].map((c) => (
                <Pressable key={c.label} onPress={() => setUnassignedOnly(c.on)} accessibilityRole="button" accessibilityState={{ selected: unassignedOnly === c.on }}
                  style={[styles.chip, unassignedOnly === c.on && styles.chipOn]} testID={c.on ? "caseload-filter-unassigned" : "caseload-filter-all"}>
                  <Text style={[styles.chipText, unassignedOnly === c.on && styles.chipTextOn]}>{c.label}</Text>
                </Pressable>
              ))}
            </View>
          )}
        </View>
      }
      ListEmptyComponent={
        worker ? (
          <EmptyState icon="people-outline" title="No participants assigned yet" subtitle="Your Service Coordinator will assign the participants you work with." />
        ) : !q.data.configured ? (
          <EmptyState icon="link-outline" title="Waiting for Jotform" subtitle="Case notes will appear here once your admin connects the Jotform account." />
        ) : (
          <EmptyState icon="people-outline" title="No participants yet" subtitle="Add a participant, or they'll appear once a case note is submitted for them. Pull down to refresh." />
        )
      }
      renderItem={({ item }) => {
        const expanded = open === item.name;
        return (
          <View style={styles.card} testID={`caseload-participant-${item.name}`}>
            <Pressable onPress={() => setOpen(expanded ? null : item.name)} style={styles.head} accessibilityLabel={`${item.name}, ${item.count} notes`}>
              <Avatar name={item.name} size={44} />
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.name}</Text>
                {!!item.birthday && (
                  <View style={styles.bday} testID={`caseload-birthday-${item.name}`}>
                    <Text style={styles.bdayText}>
                      🎂 {item.birthday.in_days === 0 ? `Birthday today! Turns ${item.birthday.turns}` : `Birthday ${item.birthday.in_days === 1 ? "tomorrow" : `in ${item.birthday.in_days} days`} · turns ${item.birthday.turns}`}
                    </Text>
                  </View>
                )}
                <Text style={styles.meta}>
                  {item.count ? `${item.count} note${item.count > 1 ? "s" : ""} · last ${formatDate(item.last_date)}` : "No notes yet"}
                  {!worker && item.participant_id ? ` · ${item.assigned.length} Support Worker${item.assigned.length === 1 ? "" : "s"}` : ""}
                </Text>
              </View>
              <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={20} color={colors.muted} />
            </Pressable>
            {expanded && (
              <View style={{ gap: 8 }}>
                {item.handover && (
                  <View style={styles.handover} testID={`caseload-handover-${item.name}`}>
                    <View style={styles.aiHead}>
                      <Ionicons name="swap-horizontal" size={16} color={colors.brandPrimary} />
                      <Text style={styles.aiTitle}>Latest shift handover</Text>
                      <Text style={styles.meta}>{formatDate(item.handover.date)}</Text>
                    </View>
                    {!!item.handover.coordinator && <Text style={styles.meta}>From {item.handover.coordinator}</Text>}
                    {item.handover.fields.filter((f: any) => !/name|email/i.test(f.label)).slice(0, 10).map((f: any, i: number) => (
                      <Text key={i} style={styles.field}><Text style={styles.fieldLabel}>{f.label}: </Text>{f.value}</Text>
                    ))}
                    <HandoverPhotos participant={item.name} handoverId={item.handover.id} photos={item.handover.photos ?? []}
                      myId={user?.user_id} canManage={q.data.can_manage} onChange={q.refetch} />
                    {item.handover.read_by_me ? (
                      <View style={styles.aiHead} testID={`caseload-handover-read-${item.name}`}>
                        <Ionicons name="checkmark-circle" size={18} color={colors.successText} />
                        <Text style={styles.meta}>You&apos;ve read this handover</Text>
                      </View>
                    ) : (
                      <Button label="I've read it" icon="checkmark-done-outline" loading={acking === item.handover.id}
                        onPress={() => ack(item)} testID={`caseload-handover-ack-${item.name}`} />
                    )}
                    {!worker && item.handover.acks && (
                      <Text style={styles.meta} testID={`caseload-handover-status-${item.name}`}>
                        {item.handover.acks.length ? `Read by ${item.handover.acks.map((a: any) => a.name).join(", ")}` : "Nobody has marked it read yet"}
                        {item.handover.waiting?.length ? ` · Waiting on ${item.handover.waiting.join(", ")}` : ""}
                      </Text>
                    )}
                  </View>
                )}
                <Button label="Write a case note" icon="create-outline" onPress={() => setWriting(item.name)} testID={`caseload-write-${item.name}`} />
                {item.participant_id && (
                  <Button label="Participant profile" icon="person-circle-outline" variant="secondary"
                    onPress={() => router.push(`/participant/${item.participant_id}`)} testID={`caseload-profile-${item.name}`} />
                )}
                {q.data.can_manage && item.participant_id && (
                  <>
                    {!!item.assigned.length && (
                      <View style={styles.introList} testID={`caseload-intro-status-${item.name}`}>
                        <Text style={styles.meta}>Assigned Support Workers · intro read?</Text>
                        {item.assigned.map((a: any) => (
                          <View key={a.user_id} style={styles.aiHead}>
                            <Ionicons name={a.intro_read ? "checkmark-circle" : "time-outline"} size={16}
                              color={a.intro_read ? colors.successText : colors.muted} />
                            <Text style={[styles.field, { flex: 1 }]}>{a.name}</Text>
                            {a.intro_read ? <Text style={styles.meta}>Read intro</Text> : (
                              <>
                                <Text style={styles.meta}>Not read</Text>
                                <NudgeButton participantId={item.participant_id} worker={a} onDone={q.refetch} />
                              </>
                            )}
                          </View>
                        ))}
                      </View>
                    )}
                    <View style={styles.manageRow}>
                      <Button label="Assign Support Workers" icon="people-outline" variant="secondary" onPress={() => setAssigning(item)} style={{ flex: 1 }} testID={`caseload-assign-${item.name}`} />
                      <Pressable onPress={() => setRemoving(item)} style={styles.trash} accessibilityLabel={`Remove ${item.name}`} testID={`caseload-remove-${item.name}`}>
                        <Ionicons name="trash-outline" size={20} color={colors.errorText} />
                      </Pressable>
                    </View>
                  </>
                )}
                {q.data.can_manage && !!item.pending?.length && item.pending.map((pn: any) => (
                  <View key={pn.start_id} style={styles.pendingRow} testID={`caseload-pending-${item.name}`}>
                    <Ionicons name="hourglass-outline" size={16} color={colors.muted} />
                    <Text style={[styles.meta, { flex: 1 }]}>{pn.name} started {/^[aeiou]/i.test(pn.form) ? "an" : "a"} {pn.form} {formatDate(pn.started_at)} and hasn&apos;t submitted it</Text>
                    <Pressable onPress={() => clearPending(pn.start_id)} style={styles.clearBtn} accessibilityRole="button" testID={`caseload-pending-clear-${pn.start_id}`}>
                      <Text style={styles.templateText}>Release</Text>
                    </Pressable>
                  </View>
                ))}
                {q.data.can_manage && !item.participant_id && (
                  <Text style={styles.meta}>Only in case notes. Add {item.name} as a participant to assign Support Workers.</Text>
                )}
              </View>
            )}
            {expanded && !worker && item.count > 0 && (
              <View style={styles.aiBox} testID={`caseload-summary-box-${item.name}`}>
                {summaries[item.name] ? (
                  <>
                    <View style={styles.aiHead}>
                      <Ionicons name="sparkles" size={16} color={colors.brandPrimary} />
                      <Text style={styles.aiTitle}>AI summary</Text>
                      <Pressable onPress={() => summarise(item.name)} hitSlop={10} style={styles.aiRedo} testID={`caseload-summary-refresh-${item.name}`}>
                        <Ionicons name="refresh" size={18} color={colors.brandPrimary} />
                      </Pressable>
                    </View>
                    <Text style={styles.field} testID={`caseload-summary-text-${item.name}`}>{summaries[item.name]}</Text>
                    <Text style={styles.aiNote}>AI can make mistakes. Check the notes below before acting.</Text>
                    <Button label="Export PDF for plan review" icon="document-text-outline" variant="secondary"
                      onPress={() => openLink(`${API_URL}/caseload/summary/pdf?name=${encodeURIComponent(item.name)}&token=${encodeURIComponent(getApiToken() ?? "")}`)}
                      testID={`caseload-summary-pdf-${item.name}`} />
                    <Button label="Email to support team" icon="mail-outline" variant="secondary"
                      onPress={() => setEmailing(item.name)} testID={`caseload-summary-email-${item.name}`} />
                  </>
                ) : (
                  <Button label={summarising === item.name ? "Summarising…" : "Summarise with AI"} icon="sparkles-outline" variant="secondary"
                    loading={summarising === item.name} onPress={() => summarise(item.name)} testID={`caseload-summarise-${item.name}`} />
                )}
              </View>
            )}
            {expanded && item.notes.map((n: any) => (
              <View key={n.id} style={styles.note} testID={`caseload-note-${n.id}`}>
                <Text style={styles.noteDate}>{formatDate(n.date)}{n.coordinator ? ` · ${n.coordinator}` : ""}</Text>
                {!!n.source && <Text style={styles.meta}>{n.source}</Text>}
                {n.fields.slice(0, 8).map((f: any, i: number) => (
                  <Text key={i} style={styles.field}><Text style={styles.fieldLabel}>{f.label}: </Text>{f.value}</Text>
                ))}
              </View>
            ))}
          </View>
        );
      }}
    />
    <StaffEmailSheet participant={emailing} onClose={() => setEmailing(null)} />
    <AddParticipantSheet visible={adding} onClose={() => setAdding(false)} onDone={q.refetch} />
    <AssignSheet participant={assigning} onClose={() => setAssigning(null)} onDone={q.refetch} />
    <CaseFormsSheet participant={writing} worker={worker} onClose={() => setWriting(null)} />
    <ConfirmSheet visible={!!removing} title={`Remove ${removing?.name ?? ""}?`}
      sub="They'll be taken off the participant list and Support Workers will lose access. Case notes in Jotform aren't deleted."
      confirmLabel="Remove participant" busy={removeBusy} onConfirm={remove} onClose={() => setRemoving(null)} />
    <ImportResultSheet result={imported} onClose={() => setImported(null)} />
    <HourSheet visible={pickingHour} current={settings.data?.reminder_hour ?? 18} onPick={saveHour} onClose={() => setPickingHour(false)} />
    <DaysOffSheet visible={daysOffOpen} onClose={() => { setDaysOffOpen(false); q.refetch(); }} />
    <IntroSheet participantId={q.data.intros?.find((i: string) => !introDone.includes(i)) ?? null}
      onDone={() => { setIntroDone((d) => [...d, q.data.intros.find((i: string) => !d.includes(i))]); q.refetch(); }}
      onOpenProfile={(id) => router.push(`/participant/${id}`)} />
    </>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  newNote: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 48, borderRadius: 14, backgroundColor: c.brandPrimary },
  newNoteText: { fontSize: 15, fontWeight: "700", color: c.onBrandPrimary },
  search: { minHeight: 44, borderRadius: 12, backgroundColor: c.surface, paddingHorizontal: 14, fontSize: 15, color: c.onSurface, borderWidth: 1, borderColor: c.border },
  card: { backgroundColor: c.surface, borderRadius: 14, padding: 14, gap: 10 },
  head: { flexDirection: "row", alignItems: "center", gap: 12, minHeight: 48 },
  name: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted },
  note: { backgroundColor: c.surfaceSecondary, borderRadius: 12, padding: 12, gap: 4 },
  noteDate: { fontSize: 13, fontWeight: "700", color: c.brandPrimary },
  field: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
  fieldLabel: { fontWeight: "700", color: c.onSurfaceSecondary },
  manageRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  trash: { width: 48, height: 48, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: c.surfaceSecondary },
  introList: { gap: 4, backgroundColor: c.surfaceSecondary, borderRadius: 12, padding: 10 },
  streak: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 16, padding: 14 },
  streakLinks: { flexDirection: "row", gap: 16, marginTop: 2 },
  chips: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  chip: { minHeight: 44, paddingHorizontal: 14, borderRadius: 22, justifyContent: "center", backgroundColor: c.surface },
  chipOn: { backgroundColor: c.brandPrimary },
  chipText: { fontSize: 13, fontWeight: "600", color: c.onSurface },
  chipTextOn: { color: c.onBrandPrimary },
  pendingRow: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: c.warningSoft, borderRadius: 10, padding: 8 },
  clearBtn: { minHeight: 44, paddingHorizontal: 10, justifyContent: "center" },
  templateLink: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 36, alignSelf: "flex-start" },
  templateText: { fontSize: 13, fontWeight: "600", color: c.brandPrimary },
  handover: { backgroundColor: c.warningSoft, borderRadius: 12, padding: 12, gap: 4, borderLeftWidth: 4, borderLeftColor: c.brandPrimary },
  aiBox: { backgroundColor: c.brandTertiary, borderRadius: 12, padding: 12, gap: 6 },
  aiHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  aiTitle: { flex: 1, fontSize: 14, fontWeight: "700", color: c.brandPrimary },
  aiRedo: { width: 44, height: 32, alignItems: "flex-end", justifyContent: "center" },
  aiNote: { fontSize: 12, color: c.muted },
  reportBox: { backgroundColor: c.surface, borderRadius: 14, padding: 12, gap: 6 },
  bday: { alignSelf: "flex-start", backgroundColor: c.brandTertiary, borderRadius: 10, paddingHorizontal: 8, paddingVertical: 2, marginVertical: 2 },
  bdayText: { fontSize: 12, fontWeight: "700", color: c.brandPrimary },
}));
