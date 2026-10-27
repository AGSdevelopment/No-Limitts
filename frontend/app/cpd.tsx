import { useState } from "react";
import { FlatList, Modal, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { Stack } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, Chip, ConfirmSheet, EmptyState, ErrorState, Field, IconBox, Ionicons, Loading, formatDate, isoDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Tab = "log" | "resources" | "team";
const CATEGORIES = ["Course", "Webinar", "Conference", "Reading", "Supervision", "Other"];
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export default function Cpd() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("log");
  const [adding, setAdding] = useState(false);
  const [del, setDel] = useState<{ kind: "log" | "res"; id: string } | null>(null);
  const logs = useQuery<any>({ queryKey: ["cpd", tab === "team" ? "all" : "mine"], queryFn: () => api(`/cpd?scope=${tab === "team" ? "all" : "mine"}`), enabled: tab !== "resources" });
  const res = useQuery<any[]>({ queryKey: ["cpd-resources"], queryFn: () => api("/cpd/resources"), enabled: tab === "resources" });

  const remove = async () => {
    if (!del) return;
    try {
      await api(del.kind === "log" ? `/cpd/${del.id}` : `/cpd/resources/${del.id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: [del.kind === "log" ? "cpd" : "cpd-resources"] });
      toast("Deleted", "info");
    } catch (e: any) {
      toast(e.message, "error");
    }
    setDel(null);
  };

  const active = tab === "resources" ? res : logs;
  const addLabel = tab === "resources" ? "Add resource" : "Log CPD";

  return (
    <View style={styles.root} testID="cpd-screen">
      <Stack.Screen
        options={{
          headerRight:
            tab === "log" || (tab === "resources" && isAdmin)
              ? () => (
                  <Pressable testID="cpd-add-button" onPress={() => setAdding(true)} hitSlop={10} accessibilityLabel={addLabel}>
                    <Ionicons name="add-circle" size={30} color={colors.brandPrimary} style={{ marginRight: 8 }} />
                  </Pressable>
                )
              : undefined,
        }}
      />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow} contentContainerStyle={styles.chipContent}>
        <Chip label="My CPD" selected={tab === "log"} onPress={() => setTab("log")} testID="cpd-tab-log" />
        <Chip label="Resources" selected={tab === "resources"} onPress={() => setTab("resources")} testID="cpd-tab-resources" />
        {isAdmin && <Chip label="Team hours" selected={tab === "team"} onPress={() => setTab("team")} testID="cpd-tab-team" />}
      </ScrollView>
      {active.isLoading ? (
        <Loading />
      ) : active.isError ? (
        <ErrorState message="Couldn't load CPD." onRetry={() => active.refetch()} />
      ) : tab === "resources" ? (
        <FlatList
          data={res.data}
          keyExtractor={(r) => r.resource_id}
          contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={res.isRefetching} onRefresh={() => res.refetch()} tintColor={colors.brandPrimary} />}
          ListEmptyComponent={<EmptyState icon="school-outline" title="No CPD resources yet" subtitle={isAdmin ? "Add courses, webinars and links for the team." : "Your managers will share CPD courses and links here."} testID="cpd-resources-empty" />}
          renderItem={({ item }) => (
            <Pressable testID={`cpd-resource-${item.resource_id}`} onPress={() => item.url && openLink(item.url)} style={styles.card}>
              <IconBox name="school-outline" size={40} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.title}>{item.title}</Text>
                {!!item.category && <Text style={styles.sub}>{item.category}</Text>}
                {!!item.description && <Text style={styles.desc} numberOfLines={3}>{item.description}</Text>}
                {!!item.url && <Text style={styles.link} numberOfLines={1}>Open link</Text>}
              </View>
              {isAdmin && (
                <Pressable testID={`cpd-resource-delete-${item.resource_id}`} onPress={() => setDel({ kind: "res", id: item.resource_id })} hitSlop={6} style={styles.iconBtn}>
                  <Ionicons name="trash-outline" size={20} color={colors.muted} />
                </Pressable>
              )}
            </Pressable>
          )}
        />
      ) : (
        <FlatList
          data={tab === "team" ? logs.data?.team_totals : logs.data?.logs}
          keyExtractor={(l) => l.log_id ?? l.user_id}
          contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={logs.isRefetching} onRefresh={() => logs.refetch()} tintColor={colors.brandPrimary} />}
          ListHeaderComponent={
            tab === "log" ? (
              <View style={styles.total} testID="cpd-year-total">
                <Text style={styles.totalNum}>{logs.data?.year_hours ?? 0}</Text>
                <Text style={styles.totalLabel}>CPD hours logged in {logs.data?.year}</Text>
              </View>
            ) : (
              <Text style={styles.teamHead}>Hours logged in {logs.data?.year}</Text>
            )
          }
          ListEmptyComponent={
            <EmptyState
              icon="time-outline"
              title={tab === "team" ? "No CPD logged this year" : "No CPD logged yet"}
              subtitle={tab === "log" ? "Tap + to record a course, webinar or other learning." : undefined}
              testID="cpd-empty"
            />
          }
          renderItem={({ item }) =>
            tab === "team" ? (
              <View style={styles.card} testID={`cpd-team-${item.user_id}`}>
                <Text style={[styles.title, { flex: 1 }]}>{item.user_name}</Text>
                <Text style={styles.hours}>{Math.round(item.hours * 100) / 100} h</Text>
              </View>
            ) : (
              <View style={styles.card} testID={`cpd-log-${item.log_id}`}>
                <View style={styles.hoursBox}>
                  <Text style={styles.hoursBig}>{item.hours}</Text>
                  <Text style={styles.hoursUnit}>hrs</Text>
                </View>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={styles.title}>{item.title}</Text>
                  <Text style={styles.sub}>{[item.category, item.provider, formatDate(item.date)].filter(Boolean).join(" · ")}</Text>
                  {!!item.notes && <Text style={styles.desc} numberOfLines={2}>{item.notes}</Text>}
                </View>
                <Pressable testID={`cpd-log-delete-${item.log_id}`} onPress={() => setDel({ kind: "log", id: item.log_id })} hitSlop={6} style={styles.iconBtn}>
                  <Ionicons name="trash-outline" size={20} color={colors.muted} />
                </Pressable>
              </View>
            )
          }
        />
      )}
      <AddSheet kind={tab === "resources" ? "resource" : "log"} visible={adding} onClose={() => setAdding(false)} />
      <ConfirmSheet visible={!!del} title="Delete this?" message="This can't be undone." confirmLabel="Delete" onConfirm={remove} onClose={() => setDel(null)} />
    </View>
  );
}

function AddSheet({ kind, visible, onClose }: { kind: "log" | "resource"; visible: boolean; onClose: () => void }) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [provider, setProvider] = useState("");
  const [date, setDate] = useState(isoDate(new Date()));
  const [hours, setHours] = useState("");
  const [category, setCategory] = useState("");
  const [notes, setNotes] = useState("");
  const [url, setUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setTitle(""); setProvider(""); setHours(""); setCategory(""); setNotes(""); setUrl(""); setError(null);
    setDate(isoDate(new Date()));
  };
  const save = async () => {
    setError(null);
    if (!title.trim()) return setError(kind === "log" ? "Enter what you did." : "Enter a title.");
    if (kind === "log") {
      if (!DATE_RE.test(date)) return setError("Date must be YYYY-MM-DD.");
      const h = parseFloat(hours.replace(",", "."));
      if (!h || h <= 0) return setError("Enter the number of hours.");
    }
    setSaving(true);
    try {
      if (kind === "log") {
        await api("/cpd", { method: "POST", body: { title, provider, date, hours: parseFloat(hours.replace(",", ".")), category, notes } });
        qc.invalidateQueries({ queryKey: ["cpd"] });
        toast("CPD logged");
      } else {
        await api("/cpd/resources", { method: "POST", body: { title, description: notes, url, category } });
        qc.invalidateQueries({ queryKey: ["cpd-resources"] });
        toast("Resource added");
      }
      reset();
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <KeyboardAwareScrollView style={styles.sheet} contentContainerStyle={{ padding: 20, paddingBottom: insets.bottom + 24 }} keyboardShouldPersistTaps="handled" bottomOffset={24} testID="cpd-add-sheet">
        <View style={styles.sheetHead}>
          <Text style={styles.sheetTitle}>{kind === "log" ? "Log CPD" : "Add CPD resource"}</Text>
          <Pressable onPress={onClose} hitSlop={10} style={styles.iconBtn} testID="cpd-add-close">
            <Ionicons name="close" size={24} />
          </Pressable>
        </View>
        <Field label={kind === "log" ? "What did you do?" : "Title"} value={title} onChangeText={setTitle} placeholder={kind === "log" ? "e.g. AAC in early intervention webinar" : "e.g. Speech Pathology Australia webinars"} testID="cpd-title-input" />
        <Text style={styles.label}>Type</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }} style={{ marginBottom: 16 }}>
          {CATEGORIES.map((c) => (
            <Chip key={c} label={c} selected={category === c} onPress={() => setCategory(category === c ? "" : c)} testID={`cpd-category-${c}`} />
          ))}
        </ScrollView>
        {kind === "log" ? (
          <>
            <Field label="Provider (optional)" value={provider} onChangeText={setProvider} placeholder="e.g. Speech Pathology Australia" testID="cpd-provider-input" />
            <Field label="Date (YYYY-MM-DD)" value={date} onChangeText={setDate} autoCapitalize="none" testID="cpd-date-input" />
            <Field label="Hours" value={hours} onChangeText={setHours} keyboardType="decimal-pad" placeholder="e.g. 1.5" testID="cpd-hours-input" />
            <Field label="Notes (optional)" value={notes} onChangeText={setNotes} multiline placeholder="What you learned" testID="cpd-notes-input" />
          </>
        ) : (
          <>
            <Field label="Link (optional)" value={url} onChangeText={setUrl} autoCapitalize="none" keyboardType="url" placeholder="https://…" testID="cpd-url-input" />
            <Field label="Description (optional)" value={notes} onChangeText={setNotes} multiline testID="cpd-desc-input" />
          </>
        )}
        {error && <Text style={styles.error} testID="cpd-add-error">{error}</Text>}
        <Button label={kind === "log" ? "Save CPD" : "Add resource"} loading={saving} onPress={save} testID="cpd-save-button" />
      </KeyboardAwareScrollView>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  chipRow: { flexGrow: 0, height: 56, backgroundColor: c.surface },
  chipContent: { paddingHorizontal: 16, gap: 8, alignItems: "center" },
  card: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 14, padding: 14, minHeight: 56 },
  title: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  desc: { fontSize: 14, color: c.onSurfaceSecondary, marginTop: 2 },
  link: { fontSize: 14, fontWeight: "600", color: c.brandPrimary, marginTop: 4 },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  total: { backgroundColor: c.brandPrimary, borderRadius: 16, padding: 20, marginBottom: 6, gap: 4 },
  totalNum: { fontSize: 40, fontWeight: "800", color: c.onBrandPrimary },
  totalLabel: { fontSize: 15, color: c.onBrandPrimary, opacity: 0.9 },
  teamHead: { fontSize: 13, fontWeight: "600", color: c.muted, textTransform: "uppercase", marginLeft: 4, marginBottom: 4 },
  hours: { fontSize: 16, fontWeight: "700", color: c.brandPrimary },
  hoursBox: { width: 52, height: 52, borderRadius: 12, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  hoursBig: { fontSize: 17, fontWeight: "800", color: c.brandPrimary },
  hoursUnit: { fontSize: 11, color: c.brandPrimary },
  sheet: { flex: 1, backgroundColor: c.surface },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 16 },
  sheetTitle: { fontSize: 20, fontWeight: "700", color: c.onSurface },
  label: { fontSize: 13, fontWeight: "600", color: c.onSurfaceSecondary, marginBottom: 8 },
  error: { fontSize: 14, color: c.errorText, marginBottom: 12 },
}));
