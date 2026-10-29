import { useMemo, useState } from "react";
import { FlatList, Modal, Pressable, View } from "react-native";
import { Text, TextInput } from "@/src/components/text";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, Field, Ionicons, dmyToIso, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const isoToDmy = (iso?: string) => (iso ? iso.split("-").reverse().join("-") : "");

// Probation start/end on the admin staff profile.
export function ProbationCard({ s, onSaved }: { s: any; onSaved: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [start, setStart] = useState(isoToDmy(s.start_date));
  const [end, setEnd] = useState(isoToDmy(s.probation_end));
  const [saving, setSaving] = useState(false);
  const days = s.probation_end ? Math.ceil((new Date(`${s.probation_end}T00:00:00`).getTime() - Date.now()) / 86400000) : null;

  const save = async () => {
    const sIso = start.trim() ? dmyToIso(start) : null;
    const eIso = end.trim() ? dmyToIso(end) : null;
    if ((start.trim() && !sIso) || (end.trim() && !eIso)) return toast("Enter dates as dd-mm-yyyy", "error");
    if (!sIso && !eIso) return toast("Enter a start date or probation end date", "error");
    setSaving(true);
    try {
      // a new start date with an unchanged end date recalculates 12 months from the start
      const endChanged = eIso && eIso !== s.probation_end;
      await api(`/staff/${s.user_id}/probation`, { method: "PATCH", body: { start_date: sIso, probation_end: endChanged || !sIso ? eIso : null } });
      toast("Probation dates saved", "success");
      setEditing(false);
      onSaved();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={styles.card} testID="probation-card">
      <View style={styles.row}>
        <Ionicons name="hourglass-outline" size={22} color={colors.brandPrimary} />
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Probation</Text>
          {s.probation_end ? (
            <Text style={[styles.sub, days !== null && days <= 14 && days >= 0 && { color: colors.warningText }]} testID="probation-summary">
              {s.start_date ? `Started ${formatDate(s.start_date)} · ` : ""}Ends {formatDate(s.probation_end)}
              {days === null ? "" : days < 0 ? " · finished" : ` · ${days} days left`}
            </Text>
          ) : (
            <Text style={styles.sub}>No probation dates set</Text>
          )}
        </View>
        {!editing && (
          <Pressable onPress={() => setEditing(true)} style={styles.iconBtn} accessibilityLabel="Edit probation" testID="probation-edit">
            <Ionicons name="create-outline" size={20} color={colors.brandPrimary} />
          </Pressable>
        )}
      </View>
      {editing && (
        <View style={{ gap: 10 }}>
          <Field label="Start date (dd-mm-yyyy)" value={start} onChangeText={setStart} placeholder="e.g. 03-11-2026" keyboardType="numbers-and-punctuation" testID="probation-start" />
          <Field label="Probation ends (dd-mm-yyyy)" value={end} onChangeText={setEnd} placeholder="Leave as is for 12 months from start" keyboardType="numbers-and-punctuation" testID="probation-end" />
          <View style={styles.row}>
            <Button label="Cancel" variant="ghost" onPress={() => setEditing(false)} style={{ flex: 1 }} testID="probation-cancel" />
            <Button label="Save" loading={saving} onPress={save} style={{ flex: 1 }} testID="probation-save" />
          </View>
        </View>
      )}
    </View>
  );
}

// Name, email and job title on the admin staff profile.
export function DetailsCard({ s, onSaved }: { s: any; onSaved: () => void }) {
  const { user: viewer } = useAuth();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ name: s.name ?? "", email: s.email ?? "", job_title: s.job_title ?? "" });
  const [saving, setSaving] = useState(false);
  const reset = () => setForm({ name: s.name ?? "", email: s.email ?? "", job_title: s.job_title ?? "" });

  const save = async () => {
    setSaving(true);
    try {
      await api(`/users/${s.user_id}`, { method: "PATCH", body: form });
      toast("Details saved", "success");
      setEditing(false);
      onSaved();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={styles.card} testID="details-card">
      <View style={styles.row}>
        <Ionicons name="person-outline" size={22} color={colors.brandPrimary} />
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Details</Text>
          <Text style={styles.sub} testID="details-summary">{s.job_title || "No job title"}</Text>
        </View>
        {!editing && (viewer?.user_type === "executive" || s.user_type !== "executive" || viewer?.user_id === s.user_id) && (
          <Pressable onPress={() => { reset(); setEditing(true); }} style={styles.iconBtn} accessibilityLabel="Edit details" testID="details-edit">
            <Ionicons name="create-outline" size={20} color={colors.brandPrimary} />
          </Pressable>
        )}
      </View>
      {editing && (
        <View style={{ gap: 10 }}>
          <Field label="Full name" value={form.name} onChangeText={(v) => setForm({ ...form, name: v })} testID="details-name" />
          <Field label="Email" value={form.email} onChangeText={(v) => setForm({ ...form, email: v })} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" testID="details-email" />
          {form.email.trim().toLowerCase() !== (s.email ?? "") && (
            <Text style={styles.sub} testID="details-email-note">
              {s.user_type === "support_worker" ? "They'll sign in with this new email from now on (same password)." : "This must match their Microsoft work email, or they won't be able to sign in."}
            </Text>
          )}
          <Field label="Job title" value={form.job_title} onChangeText={(v) => setForm({ ...form, job_title: v })} placeholder="e.g. Support Worker" testID="details-job" />
          <View style={styles.row}>
            <Button label="Cancel" variant="ghost" onPress={() => { reset(); setEditing(false); }} style={{ flex: 1 }} testID="details-cancel" />
            <Button label="Save" loading={saving} disabled={!form.name.trim() || !form.email.trim()} onPress={save} style={{ flex: 1 }} testID="details-save" />
          </View>
        </View>
      )}
    </View>
  );
}

// Birthday (day + month only) on the admin staff profile; shown to the team on the day.
export function BirthdayCard({ s, onSaved }: { s: any; onSaved: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(s.birthday ? s.birthday.split("-").reverse().join("-") : "");
  const [saving, setSaving] = useState(false);
  const label = s.birthday
    ? new Date(2000, Number(s.birthday.slice(0, 2)) - 1, Number(s.birthday.slice(3))).toLocaleDateString(undefined, { day: "numeric", month: "long" })
    : null;

  const save = async () => {
    setSaving(true);
    try {
      await api(`/staff/${s.user_id}/birthday`, { method: "PATCH", body: { birthday: value.trim() || null } });
      toast(value.trim() ? "Birthday saved" : "Birthday removed", "success");
      setEditing(false);
      onSaved();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={styles.card} testID="birthday-card">
      <View style={styles.row}>
        <Ionicons name="gift-outline" size={22} color={colors.accent} />
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Birthday</Text>
          <Text style={styles.sub} testID="birthday-summary">{label ?? "Not set"}</Text>
        </View>
        {!editing && (
          <Pressable onPress={() => setEditing(true)} style={styles.iconBtn} accessibilityLabel="Edit birthday" testID="birthday-edit">
            <Ionicons name="create-outline" size={20} color={colors.brandPrimary} />
          </Pressable>
        )}
      </View>
      {editing && (
        <View style={{ gap: 10 }}>
          <Field label="Birthday (dd-mm, no year)" value={value} onChangeText={setValue} placeholder="e.g. 14-03 · leave empty to remove" keyboardType="numbers-and-punctuation" testID="birthday-input" />
          <View style={styles.row}>
            <Button label="Cancel" variant="ghost" onPress={() => { setValue(s.birthday ? s.birthday.split("-").reverse().join("-") : ""); setEditing(false); }} style={{ flex: 1 }} testID="birthday-cancel" />
            <Button label="Save" loading={saving} onPress={save} style={{ flex: 1 }} testID="birthday-save" />
          </View>
        </View>
      )}
    </View>
  );
}

// Starter buddy on the admin staff profile.
export function BuddyCard({ s, onSaved }: { s: any; onSaved: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const insets = useSafeAreaInsets();
  const [picking, setPicking] = useState(false);
  const [search, setSearch] = useState("");
  const users = useQuery<any[]>({ queryKey: ["users"], queryFn: () => api("/users"), enabled: picking });
  const list = useMemo(
    () => (users.data ?? []).filter((u) => u.user_id !== s.user_id && u.name.toLowerCase().includes(search.trim().toLowerCase())),
    [users.data, search, s.user_id],
  );

  const choose = async (buddyId: string | null) => {
    try {
      const r = await api(`/staff/${s.user_id}/buddy`, { method: "PUT", body: { buddy_id: buddyId } });
      toast(r.buddy_id ? (r.tasks_created ? `${r.buddy_name} is now the buddy. 3 buddy tasks were added for them.` : `${r.buddy_name} is already the buddy`) : "Buddy removed", "success");
      setPicking(false);
      onSaved();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <View style={styles.card} testID="buddy-card">
      <View style={styles.row}>
        <Ionicons name="people-outline" size={22} color={colors.brandPrimary} />
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Buddy</Text>
          <Text style={styles.sub} testID="buddy-name">{s.buddy_name ?? "No buddy yet"}</Text>
        </View>
        {!!s.buddy_id && (
          <Pressable onPress={() => choose(null)} style={styles.iconBtn} accessibilityLabel="Remove buddy" testID="buddy-remove">
            <Ionicons name="close-circle-outline" size={20} color={colors.error} />
          </Pressable>
        )}
      </View>
      <Button label={s.buddy_id ? "Change buddy" : "Choose a buddy"} icon="person-add-outline" variant="secondary" onPress={() => setPicking(true)} testID="buddy-choose" />
      <Modal visible={picking} animationType="slide" transparent onRequestClose={() => setPicking(false)}>
        <View style={styles.backdrop}>
          <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]}>
            <View style={styles.row}>
              <Text style={[styles.title, { flex: 1 }]}>Choose a buddy for {s.name.split(" ")[0]}</Text>
              <Pressable onPress={() => setPicking(false)} style={styles.iconBtn} accessibilityLabel="Close" testID="buddy-close">
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            <Text style={styles.sub}>They&apos;ll get 3 tasks: a welcome message (1 day), a coffee catch-up (1 week) and a 30-day check-in.</Text>
            <TextInput value={search} onChangeText={setSearch} placeholder="Search staff" placeholderTextColor={colors.muted} style={styles.search} testID="buddy-search" />
            <FlatList
              data={list}
              keyExtractor={(u) => u.user_id}
              style={{ flex: 1 }}
              keyboardShouldPersistTaps="handled"
              renderItem={({ item }) => (
                <Pressable onPress={() => choose(item.user_id)} style={styles.pick} testID={`buddy-pick-${item.user_id}`}>
                  <Avatar name={item.name} picture={item.picture} size={36} />
                  <Text style={[styles.pickName, { flex: 1 }]}>{item.name}</Text>
                  {item.user_id === s.buddy_id && <Ionicons name="checkmark" size={20} color={colors.brandPrimary} />}
                </Pressable>
              )}
            />
          </View>
        </View>
      </Modal>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 12, gap: 10 },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  title: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  backdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.4)" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 16, gap: 10, height: "80%" },
  search: { minHeight: 44, borderRadius: 12, backgroundColor: c.surfaceSecondary, paddingHorizontal: 12, fontSize: 16, color: c.onSurface },
  pick: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 52 },
  pickName: { fontSize: 15, fontWeight: "600", color: c.onSurface },
}));
