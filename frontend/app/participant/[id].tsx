// Participant profile: key contacts, goals and support needs so new Support Workers can get up to speed.
// Coordinators and Admins edit; assigned Support Workers, HR and Coordinators read.
import { useEffect, useState } from "react";
import { Linking, Pressable, RefreshControl, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useLocalSearchParams } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { NudgeButton } from "@/src/components/participant-sheets";
import { BirthdayWall } from "@/src/components/birthday-wall";
import { Text } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, ErrorState, Field, Ionicons, Loading, dmyToIso, formatDate, isoToDmy } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const SECTIONS = [
  { key: "about", label: "About", icon: "person-outline", placeholder: "Interests, likes and dislikes, what a good day looks like" },
  { key: "goals", label: "Goals", icon: "flag-outline", placeholder: "NDIS plan goals they're working towards" },
  { key: "support_needs", label: "Support needs", icon: "hand-left-outline", placeholder: "Daily routines and how to support them" },
  { key: "communication", label: "Communication", icon: "chatbubbles-outline", placeholder: "How they communicate and what helps" },
  { key: "health_alerts", label: "Health & alerts", icon: "medkit-outline", placeholder: "Allergies, medical conditions, risks to know about" },
] as const;

type Contact = { name: string; relationship: string; phone: string; email: string };

export default function ParticipantProfile() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const q = useQuery<any>({ queryKey: ["participant", id], queryFn: () => api(`/participants/${id}`), retry: false });
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [dob, setDob] = useState("");
  const [saving, setSaving] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [draftNote, setDraftNote] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (!q.data || editing) return;
    const p = q.data.profile;
    setForm(Object.fromEntries(SECTIONS.map((s) => [s.key, p[s.key] ?? ""])));
    setContacts(p.contacts ?? []);
    setDob(isoToDmy(p.date_of_birth ?? ""));
  }, [q.data, editing]);
  useEffect(() => {
    // A Support Worker opening the profile counts as having seen the new-participant intro
    if (q.data && !q.data.can_edit) api(`/participants/${id}/intro-seen`, { method: "POST" }).catch(() => {});
  }, [q.data, id]);

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as any)?.message ?? "Couldn't load this profile"} onRetry={q.refetch} />;
  const d = q.data;
  const p = d.profile;
  const empty = !SECTIONS.some((s) => p[s.key]) && !p.contacts.length;

  const save = async () => {
    const dobIso = dob.trim() ? dmyToIso(dob) : "";
    if (dobIso === null) return toast("Enter the date of birth as DD-MM-YYYY", "error");
    setSaving(true);
    try {
      await api(`/participants/${id}/profile`, { method: "PUT", body: { ...form, date_of_birth: dobIso, contacts } });
      await q.refetch();
      setEditing(false);
      setDraftNote("");
      toast("Profile saved", "success");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };
  const setContact = (i: number, k: keyof Contact, v: string) => setContacts((cs) => cs.map((c, j) => (j === i ? { ...c, [k]: v } : c)));
  const draftWithAI = async () => {
    setDrafting(true);
    try {
      const r = await api<any>(`/participants/${id}/profile/draft`, { method: "POST" });
      setEditing(true);
      // Fill only empty sections so nothing the coordinator already wrote is overwritten
      setForm((f) => Object.fromEntries(SECTIONS.map((s) => [s.key, f[s.key]?.trim() ? f[s.key] : r[s.key] ?? ""])));
      setContacts((cs) => [...cs, ...r.contacts.filter((c: Contact) => !cs.some((x) => x.name.toLowerCase() === c.name.toLowerCase()))]);
      setDraftNote(`AI draft from ${r.note_count} case note${r.note_count === 1 ? "" : "s"}. Empty sections were filled in. Check everything before saving.`);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setDrafting(false);
    }
  };

  return (
    <KeyboardAwareScrollView
      style={styles.root}
      contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 32 }}
      bottomOffset={24}
      keyboardShouldPersistTaps="handled"
      refreshControl={editing ? undefined : <RefreshControl refreshing={refreshing} tintColor={colors.brandPrimary}
        onRefresh={async () => { setRefreshing(true); await q.refetch(); setRefreshing(false); }} />}
      testID="participant-profile-screen"
    >
      <View style={styles.hero}>
        <Avatar name={d.name} size={64} />
        <View style={{ flex: 1 }}>
          <Text style={styles.name}>{d.name}</Text>
          <Text style={styles.meta}>{d.assigned.length ? `Support Workers: ${d.assigned.join(", ")}` : "No Support Workers assigned yet"}</Text>
          {!!d.birthday && (
            <Text style={styles.bday} testID="participant-birthday">
              🎂 {d.birthday.in_days === 0 ? `Birthday today! Turns ${d.birthday.turns}` : `Birthday ${formatDate(d.birthday.date)} · turns ${d.birthday.turns}${d.birthday.in_days <= 7 ? ` (${d.birthday.in_days === 1 ? "tomorrow" : `in ${d.birthday.in_days} days`})` : ""}`}
            </Text>
          )}
          {!!p.updated_at && <Text style={styles.meta}>Updated {formatDate(p.updated_at)}{p.updated_by ? ` by ${p.updated_by}` : ""}</Text>}
        </View>
      </View>

      {!editing && <BirthdayWall participantId={d.participant_id} name={d.name} />}

      {!!d.intro_status?.length && (
        <View style={styles.card} testID="participant-intro-status">
          <Text style={styles.label}>New worker intro</Text>
          {d.intro_status.map((s: any, i: number) => (
            <View key={i} style={styles.row}>
              <Ionicons name={s.read ? "checkmark-circle" : "time-outline"} size={18} color={s.read ? colors.successText : colors.muted} />
              <Text style={[styles.body, { flex: 1 }]}>{s.name}</Text>
              {s.read ? <Text style={styles.meta}>Read</Text> : (
                <>
                  <Text style={styles.meta}>Not read yet</Text>
                  <NudgeButton participantId={d.participant_id} worker={s} onDone={q.refetch} />
                </>
              )}
            </View>
          ))}
        </View>
      )}

      {d.can_edit && !editing && (
        <>
          <Button label={empty ? "Add profile details" : "Edit profile"} icon="create-outline" variant="secondary" onPress={() => setEditing(true)} testID="participant-edit" />
          <Button label={drafting ? "Reading case notes…" : "Draft from case notes with AI"} icon="sparkles-outline" variant="ghost"
            loading={drafting} onPress={draftWithAI} testID="participant-ai-draft" />
        </>
      )}
      {editing && !!draftNote && (
        <View style={styles.aiBanner} testID="participant-ai-banner">
          <Ionicons name="sparkles" size={16} color={colors.brandPrimary} />
          <Text style={[styles.meta, { flex: 1 }]}>{draftNote}</Text>
        </View>
      )}

      {editing ? (
        <>
          <Field label="Date of birth" value={dob} onChangeText={setDob} placeholder="DD-MM-YYYY" keyboardType="numbers-and-punctuation"
            testID="participant-field-dob" />
          {SECTIONS.map((s) => (
            <Field key={s.key} label={s.label} value={form[s.key]} onChangeText={(v) => setForm((f) => ({ ...f, [s.key]: v }))}
              placeholder={s.placeholder} multiline style={styles.multi} testID={`participant-field-${s.key}`} />
          ))}
          <Text style={styles.section}>Key contacts</Text>
          {contacts.map((c, i) => (
            <View key={i} style={styles.card} testID={`participant-contact-edit-${i}`}>
              <View style={styles.row}>
                <Text style={[styles.label, { flex: 1 }]}>Contact {i + 1}</Text>
                <Pressable onPress={() => setContacts((cs) => cs.filter((_, j) => j !== i))} hitSlop={10} style={styles.iconBtn}
                  accessibilityLabel={`Remove contact ${i + 1}`} testID={`participant-contact-remove-${i}`}>
                  <Ionicons name="trash-outline" size={18} color={colors.errorText} />
                </Pressable>
              </View>
              <Field label="Name" value={c.name} onChangeText={(v) => setContact(i, "name", v)} testID={`participant-contact-name-${i}`} />
              <Field label="Relationship or role" value={c.relationship} onChangeText={(v) => setContact(i, "relationship", v)} placeholder="e.g. Mum, GP, Plan manager" testID={`participant-contact-rel-${i}`} />
              <Field label="Phone" value={c.phone} onChangeText={(v) => setContact(i, "phone", v)} keyboardType="phone-pad" testID={`participant-contact-phone-${i}`} />
              <Field label="Email" value={c.email} onChangeText={(v) => setContact(i, "email", v)} keyboardType="email-address" autoCapitalize="none" style={{ marginBottom: 0 }} testID={`participant-contact-email-${i}`} />
            </View>
          ))}
          <Button label="Add a contact" icon="add" variant="ghost" onPress={() => setContacts((cs) => [...cs, { name: "", relationship: "", phone: "", email: "" }])} testID="participant-contact-add" />
          <Button label="Save profile" icon="checkmark" loading={saving} onPress={save} testID="participant-save" />
          <Button label="Cancel" variant="ghost" onPress={() => { setEditing(false); setDraftNote(""); }} testID="participant-cancel" />
        </>
      ) : empty ? (
        <View style={styles.card}>
          <Text style={styles.meta}>{d.can_edit ? "No profile details yet. Add their goals, support needs and key contacts so new Support Workers can get up to speed." : "Your Service Coordinator hasn't added profile details yet."}</Text>
        </View>
      ) : (
        <>
          {SECTIONS.filter((s) => p[s.key]).map((s) => (
            <View key={s.key} style={[styles.card, s.key === "health_alerts" && styles.alert]} testID={`participant-section-${s.key}`}>
              <View style={styles.row}>
                <Ionicons name={s.icon} size={18} color={s.key === "health_alerts" ? colors.errorText : colors.brandPrimary} />
                <Text style={styles.label}>{s.label}</Text>
              </View>
              <Text style={styles.body}>{p[s.key]}</Text>
            </View>
          ))}
          {!!p.contacts.length && <Text style={styles.section}>Key contacts</Text>}
          {p.contacts.map((c: Contact, i: number) => (
            <View key={i} style={styles.card} testID={`participant-contact-${i}`}>
              <Text style={styles.label}>{c.name}</Text>
              {!!c.relationship && <Text style={styles.meta}>{c.relationship}</Text>}
              <View style={[styles.row, { flexWrap: "wrap" }]}>
                {!!c.phone && (
                  <Pressable onPress={() => Linking.openURL(`tel:${c.phone.replace(/\s/g, "")}`)} style={styles.chip} testID={`participant-contact-call-${i}`}>
                    <Ionicons name="call-outline" size={16} color={colors.brandPrimary} />
                    <Text style={styles.chipText}>{c.phone}</Text>
                  </Pressable>
                )}
                {!!c.email && (
                  <Pressable onPress={() => Linking.openURL(`mailto:${c.email}`)} style={styles.chip} testID={`participant-contact-email-${i}`}>
                    <Ionicons name="mail-outline" size={16} color={colors.brandPrimary} />
                    <Text style={styles.chipText}>{c.email}</Text>
                  </Pressable>
                )}
              </View>
            </View>
          ))}
        </>
      )}
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  hero: { flexDirection: "row", alignItems: "center", gap: 14, backgroundColor: c.surface, borderRadius: 16, padding: 16 },
  name: { fontSize: 20, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
  bday: { fontSize: 13, fontWeight: "700", color: c.brandPrimary, lineHeight: 18 },
  card: { backgroundColor: c.surface, borderRadius: 14, padding: 14, gap: 8 },
  alert: { borderLeftWidth: 4, borderLeftColor: c.errorText },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  label: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  body: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
  section: { fontSize: 16, fontWeight: "700", color: c.onSurface, marginTop: 4 },
  multi: { minHeight: 88, textAlignVertical: "top" },
  aiBanner: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: c.brandTertiary, borderRadius: 12, padding: 12 },
  iconBtn: { width: 44, height: 36, alignItems: "flex-end", justifyContent: "center" },
  chip: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 40, paddingHorizontal: 12, borderRadius: 20, backgroundColor: c.brandTertiary },
  chipText: { fontSize: 14, fontWeight: "600", color: c.brandPrimary },
}));
