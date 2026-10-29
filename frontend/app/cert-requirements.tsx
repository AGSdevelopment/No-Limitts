import { useState } from "react";
import { Pressable, View } from "react-native";
import { Text, TextInput } from "@/src/components/text";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { EmptyState, ErrorState, Ionicons, Loading } from "@/src/components/ui";
import { STAFF_GROUPS } from "@/src/groups";
import { makeStyles, useTheme } from "@/src/theme";

export default function CertRequirements() {
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const q = useQuery<any>({ queryKey: ["cert-requirements"], queryFn: () => api("/cert-requirements"), enabled: user?.role === "admin" });

  if (user?.role !== "admin") return <EmptyState icon="lock-closed-outline" title="Admins only" />;
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load requirements." onRetry={() => q.refetch()} />;

  return (
    <KeyboardAwareScrollView
      style={styles.root}
      contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
      keyboardShouldPersistTaps="handled"
      bottomOffset={24}
      testID="cert-requirements-screen"
    >
      <Text style={styles.intro}>
        Choose the certificates each staff group must hold. A requirement is met by any certificate that hasn't expired and whose title contains the name (e.g. &quot;First Aid&quot;).
      </Text>
      {STAFF_GROUPS.map((g) => (
        <GroupCard key={g.key} groupKey={g.key} label={g.label} names={q.data.groups?.[g.key] ?? []} />
      ))}
    </KeyboardAwareScrollView>
  );
}

function GroupCard({ groupKey, label, names }: { groupKey: string; label: string; names: string[] }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async (next: string[]) => {
    setSaving(true);
    try {
      await api("/cert-requirements", { method: "PUT", body: { staff_group: groupKey, names: next } });
      qc.invalidateQueries({ queryKey: ["cert-requirements"] });
      qc.invalidateQueries({ queryKey: ["compliance"] });
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const add = async () => {
    const n = text.trim();
    if (!n) return;
    if (names.some((x) => x.toLowerCase() === n.toLowerCase())) return toast(`${n} is already required`, "info");
    setText("");
    await save([...names, n]);
  };

  return (
    <View style={styles.card} testID={`req-group-${groupKey}`}>
      <Text style={styles.title}>{label}</Text>
      {names.length === 0 ? (
        <Text style={styles.none}>No required certificates</Text>
      ) : (
        <View style={styles.chips}>
          {names.map((n) => (
            <View key={n} style={styles.chip}>
              <Text style={styles.chipText}>{n}</Text>
              <Pressable onPress={() => save(names.filter((x) => x !== n))} hitSlop={14} style={styles.removeBtn} accessibilityLabel={`Remove ${n}`} testID={`req-remove-${groupKey}-${n}`}>
                <Ionicons name="close-circle" size={18} color={colors.brandPrimary} />
              </Pressable>
            </View>
          ))}
        </View>
      )}
      <View style={styles.addRow}>
        <TextInput
          value={text}
          onChangeText={setText}
          onSubmitEditing={add}
          placeholder="Add e.g. First Aid"
          placeholderTextColor={colors.muted}
          style={styles.input}
          returnKeyType="done"
          testID={`req-input-${groupKey}`}
        />
        <Pressable onPress={add} disabled={saving || !text.trim()} style={[styles.addBtn, (saving || !text.trim()) && { opacity: 0.5 }]} accessibilityLabel="Add requirement" testID={`req-add-${groupKey}`}>
          <Ionicons name="add" size={22} color={colors.onBrandPrimary} />
        </Pressable>
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  intro: { fontSize: 14, color: c.onSurfaceSecondary, lineHeight: 20 },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 14, gap: 10 },
  title: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  none: { fontSize: 13, color: c.muted },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { flexDirection: "row", alignItems: "center", gap: 2, backgroundColor: c.brandTertiary, borderRadius: 999, paddingLeft: 12, paddingRight: 2 },
  removeBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  chipText: { fontSize: 14, fontWeight: "600", color: c.brandPrimary },
  addRow: { flexDirection: "row", gap: 8, alignItems: "center" },
  input: { flex: 1, minHeight: 44, borderRadius: 12, backgroundColor: c.surfaceSecondary, paddingHorizontal: 12, fontSize: 16, color: c.onSurface },
  addBtn: { width: 44, height: 44, borderRadius: 12, backgroundColor: c.brandPrimary, alignItems: "center", justifyContent: "center" },
}));
