import { useState } from "react";
import { FlatList, Modal, Pressable, RefreshControl, Text, View } from "react-native";
import { Stack } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, ConfirmSheet, EmptyState, ErrorState, Field, IconBox, Ionicons, Loading } from "@/src/components/ui";
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
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [del, setDel] = useState<any>(null);
  const q = useQuery<any[]>({ queryKey: ["forms"], queryFn: () => api("/forms") });

  const open = (f: any) => {
    const sep = f.url.includes("?") ? "&" : "?";
    openLink(`${f.url}${sep}name=${encodeURIComponent(user?.name ?? "")}&email=${encodeURIComponent(user?.email ?? "")}`);
  };

  const save = async () => {
    setError(null);
    if (!title.trim() || !url.trim()) return setError("Add a title and the Jotform link.");
    setSaving(true);
    try {
      await api("/forms", { method: "POST", body: { title, url, description: desc } });
      qc.invalidateQueries({ queryKey: ["forms"] });
      toast("Form added");
      setAdding(false);
      setTitle("");
      setUrl("");
      setDesc("");
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
                <Pressable testID="forms-add-button" onPress={() => setAdding(true)} hitSlop={10} style={{ marginRight: 8 }}>
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
        <FlatList
          data={q.data}
          keyExtractor={(f) => f.form_id}
          contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
          ListEmptyComponent={
            <EmptyState
              icon="clipboard-outline"
              title="No forms yet"
              subtitle={isAdmin ? "Add your Jotform forms, like incident reports or leave requests." : "Your company's forms will show up here."}
              actionLabel={isAdmin ? "Add form" : undefined}
              onAction={() => setAdding(true)}
            />
          }
          renderItem={({ item }) => (
            <Pressable testID={`form-${item.form_id}`} onPress={() => open(item)} style={({ pressed }) => [styles.row, pressed && { opacity: 0.8 }]}>
              <IconBox name="clipboard-outline" />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.title}>{item.title}</Text>
                <Text style={styles.sub} numberOfLines={2}>{item.description || "Tap to fill in"}</Text>
              </View>
              {isAdmin ? (
                <Pressable testID={`form-delete-${item.form_id}`} hitSlop={10} onPress={() => setDel(item)} style={styles.iconBtn}>
                  <Ionicons name="trash-outline" size={20} color={colors.muted} />
                </Pressable>
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
            <Text style={styles.sheetTitle}>Add a Jotform form</Text>
            <Field label="Title" value={title} onChangeText={setTitle} placeholder="e.g. Incident report" testID="forms-title-input" />
            <Field label="Jotform link or form ID" value={url} onChangeText={setUrl} placeholder="https://form.jotform.com/…" autoCapitalize="none" autoCorrect={false} testID="forms-url-input" />
            <Field label="Description (optional)" value={desc} onChangeText={setDesc} placeholder="When to use this form" testID="forms-description-input" />
            <Text style={styles.hint}>Employees&apos; name and email are passed to the form so matching fields fill in automatically.</Text>
            {error && <Text style={styles.error} testID="forms-error">{error}</Text>}
            <Button label="Add form" loading={saving} onPress={save} testID="forms-save-button" />
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
}));
