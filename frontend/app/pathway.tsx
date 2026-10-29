import { useState } from "react";
import { Pressable, RefreshControl, View } from "react-native";
import { Text } from "@/src/components/text";
import { useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, EmptyState, ErrorState, Field, Ionicons, Loading, dmyToIso, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function Pathway() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const allowed = user?.staff_group === "emerging_therapist";
  const q = useQuery<any>({ queryKey: ["pathway"], queryFn: () => api("/pathway"), enabled: allowed });
  const [adding, setAdding] = useState(false);
  const [g, setG] = useState({ title: "", due: "", notes: "" });
  const [saving, setSaving] = useState(false);

  if (!allowed) return <EmptyState icon="lock-closed-outline" title="For Emerging Therapists" subtitle="This pathway shows for staff in the Emerging Therapists group." />;
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load your pathway." onRetry={() => q.refetch()} />;
  const d = q.data;
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["pathway"] });
  };
  const run = async (fn: () => Promise<any>) => {
    try {
      await fn();
      refresh();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const addGoal = async () => {
    if (!g.title.trim()) return toast("Describe your goal", "error");
    let due = "";
    if (g.due.trim()) {
      const iso = dmyToIso(g.due);
      if (!iso) return toast("Enter the target date as dd-mm-yyyy", "error");
      due = iso;
    }
    setSaving(true);
    try {
      await api("/pathway/goals", { method: "POST", body: { ...g, due } });
      setG({ title: "", due: "", notes: "" });
      setAdding(false);
      refresh();
      toast("Goal added", "success");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Australia/Perth" });

  return (
    <KeyboardAwareScrollView
      style={styles.root}
      contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
      keyboardShouldPersistTaps="handled"
      bottomOffset={24}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
      testID="pathway-screen"
    >
      <View style={styles.hero} testID="pathway-progress">
        <Text style={styles.heroTitle}>{d.steps_done === d.steps_total ? "Pathway complete! 🎉" : "Your growth pathway"}</Text>
        <Text style={styles.heroSub}>{d.steps_done} of {d.steps_total} supervision steps · {d.goals_done}/{d.goals.length} goals · {d.cpd_year_hours}h CPD this year</Text>
        <View style={styles.bar}>
          <View style={[styles.barFill, { width: `${Math.round((d.steps_done / d.steps_total) * 100)}%` }]} />
        </View>
      </View>

      <Text style={styles.section}>Supervision checklist</Text>
      {d.steps.map((s: any) => (
        <Pressable key={s.key} onPress={() => run(() => api(`/pathway/steps/${s.key}`, { method: "POST" }))} style={[styles.card, s.done && { opacity: 0.75 }]} testID={`pathway-step-${s.key}`}>
          <Ionicons name={s.done ? "checkmark-circle" : "ellipse-outline"} size={28} color={s.done ? colors.success : colors.brandPrimary} />
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={[styles.title, s.done && styles.doneText]}>{s.title}</Text>
            {!!s.description && <Text style={styles.sub}>{s.description}</Text>}
            {s.done && <Text style={styles.hint}>Done {formatDate(s.done_at.slice(0, 10))}</Text>}
          </View>
        </Pressable>
      ))}

      <View style={styles.sectionRow}>
        <Text style={[styles.section, { flex: 1 }]}>My CPD goals</Text>
        <Pressable onPress={() => router.push("/cpd")} style={styles.linkBtn} testID="pathway-open-cpd">
          <Text style={styles.link}>Log CPD</Text>
        </Pressable>
      </View>
      {d.goals.length === 0 && !adding && <Text style={styles.sub}>Set goals for what you want to learn this year, e.g. "Complete a sensory processing course".</Text>}
      {d.goals.map((goal: any) => {
        const overdue = !goal.done && goal.due && goal.due < today;
        return (
          <View key={goal.goal_id} style={styles.card} testID={`pathway-goal-${goal.goal_id}`}>
            <Pressable onPress={() => run(() => api(`/pathway/goals/${goal.goal_id}`, { method: "PATCH", body: { done: !goal.done } }))} style={styles.iconBtn} accessibilityLabel={goal.done ? "Mark not done" : "Mark done"} testID={`pathway-goal-toggle-${goal.goal_id}`}>
              <Ionicons name={goal.done ? "checkbox" : "square-outline"} size={26} color={goal.done ? colors.success : colors.brandPrimary} />
            </Pressable>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={[styles.title, goal.done && styles.doneText]}>{goal.title}</Text>
              {!!goal.notes && <Text style={styles.sub}>{goal.notes}</Text>}
              {!!goal.due && <Text style={[styles.hint, overdue && { color: colors.error }]}>{goal.done ? "Achieved" : overdue ? "Overdue · target" : "Target"} {formatDate(goal.due)}</Text>}
            </View>
            <Pressable onPress={() => run(() => api(`/pathway/goals/${goal.goal_id}`, { method: "DELETE" }))} style={styles.iconBtn} accessibilityLabel="Delete goal" testID={`pathway-goal-delete-${goal.goal_id}`}>
              <Ionicons name="trash-outline" size={18} color={colors.muted} />
            </Pressable>
          </View>
        );
      })}
      {adding ? (
        <View style={styles.form} testID="pathway-goal-form">
          <Field label="Goal" value={g.title} onChangeText={(v) => setG({ ...g, title: v })} placeholder="e.g. Complete a sensory processing course" testID="pathway-goal-title" />
          <Field label="Target date (dd-mm-yyyy, optional)" value={g.due} onChangeText={(v) => setG({ ...g, due: v })} placeholder="e.g. 30-09-2026" keyboardType="numbers-and-punctuation" testID="pathway-goal-due" />
          <Field label="Notes (optional)" value={g.notes} onChangeText={(v) => setG({ ...g, notes: v })} placeholder="How you'll get there" multiline testID="pathway-goal-notes" />
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Button label="Cancel" variant="ghost" onPress={() => setAdding(false)} style={{ flex: 1 }} testID="pathway-goal-cancel" />
            <Button label="Save goal" loading={saving} onPress={addGoal} style={{ flex: 1 }} testID="pathway-goal-save" />
          </View>
        </View>
      ) : (
        <Button label="Add a CPD goal" icon="add" variant="secondary" onPress={() => setAdding(true)} testID="pathway-goal-add" />
      )}
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  hero: { backgroundColor: c.brandPrimary, borderRadius: 18, padding: 20, gap: 6 },
  heroTitle: { fontSize: 20, fontWeight: "800", color: c.onBrandPrimary },
  heroSub: { fontSize: 14, color: c.onBrandPrimary, opacity: 0.9 },
  bar: { height: 10, borderRadius: 5, backgroundColor: "rgba(255,255,255,0.3)", overflow: "hidden", marginTop: 6 },
  barFill: { height: 10, borderRadius: 5, backgroundColor: c.onBrandPrimary },
  section: { fontSize: 17, fontWeight: "700", color: c.onSurface, marginTop: 8 },
  sectionRow: { flexDirection: "row", alignItems: "center" },
  card: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: c.surface, borderRadius: 16, padding: 12, minHeight: 56 },
  form: { backgroundColor: c.surface, borderRadius: 16, padding: 16 },
  title: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  doneText: { textDecorationLine: "line-through", color: c.muted },
  sub: { fontSize: 13, color: c.onSurfaceSecondary },
  hint: { fontSize: 12, color: c.brandPrimary },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  linkBtn: { minHeight: 44, paddingHorizontal: 8, justifyContent: "center" },
  link: { fontSize: 14, fontWeight: "700", color: c.brandPrimary },
}));
