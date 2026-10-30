// No Limitts app privacy policy. Open to everyone (linked from Login and Library); admins can edit the wording.
import { useState } from "react";
import { View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Text } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Button, ErrorState, Field, Loading, formatDate } from "@/src/components/ui";
import { makeStyles } from "@/src/theme";

export default function Privacy() {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const toast = useToast();
  const q = useQuery<{ text: string; updated_at: string }>({ queryKey: ["privacy"], queryFn: () => api("/privacy") });
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as any)?.message ?? "Couldn't load the privacy policy"} onRetry={q.refetch} />;

  const save = async () => {
    setSaving(true);
    try {
      await api("/privacy", { method: "PUT", body: { text: draft } });
      await q.refetch();
      setDraft(null);
      toast("Privacy policy updated", "success");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <KeyboardAwareScrollView style={styles.root} bottomOffset={24} keyboardShouldPersistTaps="handled"
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 12 }} testID="privacy-screen">
      {draft !== null ? (
        <>
          <Text style={styles.meta}>Start a line with &quot;## &quot; for a heading and &quot;- &quot; for a bullet point.</Text>
          <Field label="Privacy policy" value={draft} onChangeText={setDraft} multiline style={styles.editor} testID="privacy-editor" />
          <Button label="Save" icon="checkmark" loading={saving} disabled={!draft.trim()} onPress={save} testID="privacy-save" />
          <Button label="Cancel" variant="ghost" onPress={() => setDraft(null)} testID="privacy-cancel" />
        </>
      ) : (
        <View style={styles.card}>
          {q.data!.text.split("\n").filter((l) => l.trim()).map((line, i) =>
            line.startsWith("## ") ? (
              <Text key={i} style={[styles.heading, i === 0 && { marginTop: 0 }]} accessibilityRole="header">{line.slice(3)}</Text>
            ) : line.startsWith("- ") ? (
              <Text key={i} style={styles.body}>{"\u2022  "}{line.slice(2)}</Text>
            ) : (
              <Text key={i} style={styles.body}>{line}</Text>
            ),
          )}
          {!!q.data!.updated_at && <Text style={styles.meta}>Last updated {formatDate(q.data!.updated_at)}</Text>}
        </View>
      )}
      {user?.role === "admin" && draft === null && (
        <Button label="Edit privacy policy" icon="create-outline" variant="secondary" onPress={() => setDraft(q.data!.text)} testID="privacy-edit" />
      )}
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 18, gap: 8 },
  heading: { fontSize: 17, fontWeight: "700", color: c.brandPrimary, marginTop: 12 },
  body: { fontSize: 14, color: c.onSurface, lineHeight: 21 },
  meta: { fontSize: 13, color: c.muted },
  editor: { minHeight: 360, textAlignVertical: "top" },
}));
