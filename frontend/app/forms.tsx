import { useState } from "react";
import { Modal, Pressable, RefreshControl, SectionList, View } from "react-native";
import { Text } from "@/src/components/text";
import { Stack } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, Chip, ConfirmSheet, EmptyState, ErrorState, Field, IconBox, Ionicons, Loading } from "@/src/components/ui";
import { FORM_CATEGORIES, STAFF_GROUPS, audienceLabel } from "@/src/groups";
import { makeStyles, useTheme } from "@/src/theme";

export default function Forms() {
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [desc, setDesc] = useState("");
  const [audiences, setAudiences] = useState<string[]>([]);
  const [category, setCategory] = useState<string>("Day-to-Day");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [del, setDel] = useState<any>(null);
  const q = useQuery<any[]>({ queryKey: ["forms"], queryFn: () => api("/forms") });
  // Every category header always shows (empty ones say so) so admins can see where forms go.
  const sections = FORM_CATEGORIES.map((c) => {
    const data = (q.data ?? []).filter((f) => (f.category || "Day-to-Day") === c);
    return { title: c, data: data.length ? data : [{ form_id: `empty-${c}`, empty: true, category: c }] };
  });

  const open = (f: any) => {
    const sep = f.url.includes("?") ? "&" : "?";
    openLink(`${f.url}${sep}name=${encodeURIComponent(user?.name ?? "")}&email=${encodeURIComponent(user?.email ?? "")}`);
  };

  const startAdd = () => {
    setEditingId(null);
    setTitle("");
    setUrl("");
    setDesc("");
    setAudiences([]);
    setCategory("Day-to-Day");
    setError(null);
    setAdding(true);
  };
  const startEdit = (f: any) => {
    setEditingId(f.form_id);
    setTitle(f.title);
    setUrl(f.url);
    setDesc(f.description ?? "");
    setAudiences(f.audiences ?? []);
    setCategory(f.category || "Day-to-Day");
    setError(null);
    setAdding(true);
  };
  const toggleGroup = (key: string) =>
    setAudiences((a) => (a.includes(key) ? a.filter((k) => k !== key) : [...a, key]));

  const save = async () => {
    setError(null);
    if (!title.trim() || !url.trim()) return setError("Add a title and the Jotform link.");
    setSaving(true);
    try {
      const body = { title, url, description: desc, audiences, category };
      if (editingId) await api(`/forms/${editingId}`, { method: "PATCH", body });
      else await api("/forms", { method: "POST", body });
      qc.invalidateQueries({ queryKey: ["forms"] });
      toast(editingId ? "Form updated" : "Form added");
      setAdding(false);
      setEditingId(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    try {
      await api(`/forms/${del.form_id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["forms"] });
      toast("Form removed");
    } catch (e: any) {
      toast(e.message, "error");
    }
    setDel(null);
  };

  return (
    <View style={styles.root} testID="forms-screen">
      <Stack.Screen
        options={{
          headerRight: isAdmin
            ? () => (
                <Pressable testID="forms-add-button" onPress={startAdd} hitSlop={10} style={{ marginRight: 8 }}>
                  <Ionicons name="add-circle" size={30} color={colors.brandPrimary} />
                </Pressable>
              )
            : undefined,
        }}
      />
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Could not load forms." onRetry={() => q.refetch()} />
      ) : (
        <SectionList
          sections={sections}
          keyExtractor={(f) => f.form_id}
          stickySectionHeadersEnabled={false}
          contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
          renderSectionHeader={({ section }) => (
            <Text style={styles.sectionHeader} testID={`forms-section-${section.title}`}>
              {section.title}
            </Text>
          )}
          ListEmptyComponent={
            <EmptyState
              icon="clipboard-outline"
              title="No forms yet"
              subtitle={isAdmin ? "Add your No Limitts forms, like incident reports or leave requests." : "Your company's forms will show up here."}
              actionLabel={isAdmin ? "Add form" : undefined}
              onAction={startAdd}
            />
          }
          renderItem={({ item }) => item.empty ? (
            <Text style={styles.emptySection} testID={`forms-empty-${item.category}`}>
              {isAdmin ? "No forms yet. Tap + to add one here." : "No forms here yet."}
            </Text>
          ) : (
            <Pressable testID={`form-${item.form_id}`} onPress={() => open(item)} style={({ pressed }) => [styles.row, pressed && { opacity: 0.8 }]}>
              <IconBox name="clipboard-outline" />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.title}>{item.title}</Text>
                <Text style={styles.sub} numberOfLines={2}>{item.description || "Tap to fill in"}</Text>
                {(isAdmin || (item.audiences ?? []).length > 0) && (
                  <View style={styles.audBtn} testID={`form-audience-${item.form_id}`}>
                    <Ionicons name={(item.audiences ?? []).length ? "lock-closed" : "people"} size={13} color={colors.brandPrimary} />
                    <Text style={styles.audText} numberOfLines={2}>{audienceLabel(item.audiences)}</Text>
                  </View>
                )}
              </View>
              {isAdmin ? (
                <View style={{ flexDirection: "row" }}>
                  <Pressable testID={`form-edit-${item.form_id}`} hitSlop={6} onPress={() => startEdit(item)} style={styles.iconBtn}>
                    <Ionicons name="create-outline" size={20} color={colors.brandPrimary} />
                  </Pressable>
                  <Pressable testID={`form-delete-${item.form_id}`} hitSlop={6} onPress={() => setDel(item)} style={styles.iconBtn}>
                    <Ionicons name="trash-outline" size={20} color={colors.muted} />
                  </Pressable>
                </View>
              ) : (
                <Ionicons name="open-outline" size={20} color={colors.muted} />
              )}
            </Pressable>
          )}
        />
      )}

      <Modal visible={adding} animationType="slide" transparent onRequestClose={() => setAdding(false)}>
        <Pressable style={styles.scrim} onPress={() => setAdding(false)} testID="forms-add-backdrop" />
        <View style={styles.sheet}>
          <KeyboardAwareScrollView contentContainerStyle={{ padding: 24, paddingBottom: insets.bottom + 24 }} keyboardShouldPersistTaps="handled" bottomOffset={24}>
            <Text style={styles.sheetTitle}>{editingId ? "Edit form" : "Add a Jotform form"}</Text>
            <Field label="Title" value={title} onChangeText={setTitle} placeholder="e.g. Incident report" testID="forms-title-input" />
            <Field label="Jotform link or form ID" value={url} onChangeText={setUrl} placeholder="https://form.jotform.com/…" autoCapitalize="none" autoCorrect={false} testID="forms-url-input" />
            <Field label="Description (optional)" value={desc} onChangeText={setDesc} placeholder="When to use this form" testID="forms-description-input" />
            <Text style={styles.fieldLabel}>Section</Text>
            <View style={styles.chipWrap}>
              {FORM_CATEGORIES.map((c) => (
                <Chip key={c} label={c} selected={category === c} onPress={() => setCategory(c)} testID={`forms-category-${c}`} />
              ))}
            </View>
            <Text style={styles.fieldLabel}>Who can see it (admins always can)</Text>
            <View style={styles.groupList}>
              <Pressable testID="forms-audience-everyone" onPress={() => setAudiences([])} style={styles.groupRow}>
                <Ionicons name={audiences.length === 0 ? "radio-button-on" : "radio-button-off"} size={22} color={audiences.length === 0 ? colors.brandPrimary : colors.borderStrong} />
                <Text style={styles.groupText}>Everyone</Text>
              </Pressable>
              {STAFF_GROUPS.map((g) => {
                const on = audiences.includes(g.key);
                return (
                  <Pressable key={g.key} testID={`forms-audience-${g.key}`} onPress={() => toggleGroup(g.key)} style={styles.groupRow}>
                    <Ionicons name={on ? "checkbox" : "square-outline"} size={22} color={on ? colors.brandPrimary : colors.borderStrong} />
                    <Text style={styles.groupText}>{g.label}</Text>
                  </Pressable>
                );
              })}
            </View>
            <Text style={styles.hint}>Employees&apos; name and email are passed to the form so matching fields fill in automatically.</Text>
            {error && <Text style={styles.error} testID="forms-error">{error}</Text>}
            <Button label={editingId ? "Save changes" : "Add form"} loading={saving} onPress={save} testID="forms-save-button" />
          </KeyboardAwareScrollView>
        </View>
      </Modal>
      <ConfirmSheet visible={!!del} title="Remove form?" message={`"${del?.title ?? ""}" will no longer appear in the app.`} confirmLabel="Remove" onConfirm={remove} onClose={() => setDel(null)} />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  row: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 14, padding: 14, minHeight: 64 },
  title: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  scrim: { flex: 1, backgroundColor: c.scrim },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, maxHeight: "85%" },
  sheetTitle: { fontSize: 20, fontWeight: "700", color: c.onSurface, marginBottom: 16 },
  hint: { fontSize: 13, color: c.muted, marginBottom: 12, lineHeight: 18 },
  error: { fontSize: 14, color: c.errorText, marginBottom: 12 },
  fieldLabel: { fontSize: 13, fontWeight: "600", color: c.onSurfaceSecondary, marginBottom: 8 },
  sectionHeader: { fontSize: 13, fontWeight: "700", color: c.muted, textTransform: "uppercase", letterSpacing: 0.5, marginTop: 16, marginBottom: 8, marginLeft: 4 },
  emptySection: { fontSize: 14, color: c.muted, backgroundColor: c.surface, borderRadius: 12, padding: 14, borderWidth: 1, borderColor: c.border, borderStyle: "dashed" },
  groupList: { marginBottom: 16 },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 16 },
  groupRow: { flexDirection: "row", alignItems: "center", gap: 12, minHeight: 48, borderBottomWidth: 0.5, borderBottomColor: c.divider },
  groupText: { fontSize: 15, color: c.onSurface },
  audBtn: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4, minHeight: 28 },
  audText: { fontSize: 12, fontWeight: "600", color: c.brandPrimary },
}));
