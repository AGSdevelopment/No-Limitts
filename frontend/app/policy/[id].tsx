import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, ErrorState, Ionicons, Loading, Pill, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function PolicyDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [saving, setSaving] = useState(false);
  const q = useQuery<any[]>({ queryKey: ["policies"], queryFn: () => api("/policies") });
  const p = q.data?.find((x) => x.policy_id === id);

  const ack = async () => {
    setSaving(true);
    try {
      await api(`/policies/${id}/acknowledge`, { method: "POST" });
      await qc.invalidateQueries({ queryKey: ["policies"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast("Thanks — acknowledged");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  if (q.isLoading) return <Loading />;
  if (!p) return <ErrorState message="Policy not found." onRetry={() => q.refetch()} />;

  return (
    <View style={styles.root} testID="policy-detail-screen">
      <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 24 }}>
        <Pill label={p.category} />
        <Text style={styles.title}>{p.title}</Text>
        <Text style={styles.meta}>
          {p.author_name} · {formatDate(p.created_at)} · {p.ack_count} acknowledged
        </Text>
        <Text style={styles.body} testID="policy-content">{p.content}</Text>
      </ScrollView>
      <View style={[styles.footer, { paddingBottom: insets.bottom + 12 }]}>
        {p.acknowledged ? (
          <View style={styles.done} testID="policy-acknowledged">
            <Ionicons name="checkmark-circle" size={22} color={colors.successText} />
            <Text style={styles.doneText}>You have acknowledged this</Text>
          </View>
        ) : (
          <Button label="I have read and understood" icon="checkmark" loading={saving} onPress={ack} testID="policy-acknowledge-button" />
        )}
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  title: { fontSize: 26, fontWeight: "700", color: c.onSurface, letterSpacing: -0.5, marginTop: 12 },
  meta: { fontSize: 13, color: c.muted, marginTop: 6, marginBottom: 20 },
  body: { fontSize: 16, color: c.onSurfaceSecondary, lineHeight: 25 },
  footer: { paddingHorizontal: 16, paddingTop: 12, borderTopWidth: 0.5, borderTopColor: c.divider, backgroundColor: c.surface },
  done: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 48, borderRadius: 12, backgroundColor: c.successSoft },
  doneText: { fontSize: 15, fontWeight: "600", color: c.successText },
}));
