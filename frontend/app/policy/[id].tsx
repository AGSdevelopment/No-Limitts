import { useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { Text } from "@/src/components/text";
import { useLocalSearchParams } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { AckTrackerSheet, NewVersionSheet } from "@/src/components/policy-admin";
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
  const [tracker, setTracker] = useState(false);
  const [newVersion, setNewVersion] = useState(false);
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
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
          {p.author_name} · {p.version > 1 ? `Version ${p.version} · updated ${formatDate(p.updated_at)}` : formatDate(p.created_at)} · {p.ack_count} acknowledged
        </Text>
        {p.version > 1 && !!p.change_note && (
          <View style={styles.changeBox} testID="policy-change-note">
            <Ionicons name="refresh-circle" size={20} color={colors.brandPrimary} />
            <Text style={styles.changeText}>What changed: {p.change_note}</Text>
          </View>
        )}
        {isAdmin && (
          <View style={styles.adminRow}>
            <Button label={`Tracker (${p.ack_count})`} variant="secondary" icon="people-outline" onPress={() => setTracker(true)} testID="policy-ack-tracker-button" style={{ flex: 1 }} />
            <Button label="New version" variant="secondary" icon="cloud-upload-outline" onPress={() => setNewVersion(true)} testID="policy-new-version-button" style={{ flex: 1 }} />
          </View>
        )}
        <Text style={styles.body} testID="policy-content">{p.content}</Text>
        {(p.drive_file || p.attachment_name) && (
          <Pressable testID="policy-drive-file" onPress={() => openLink(`${API_URL}/policies/${p.policy_id}/file?token=${encodeURIComponent(getApiToken() ?? "")}`)} style={styles.driveCard}>
            <Ionicons name="document-text-outline" size={20} color={colors.brandPrimary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.driveName} numberOfLines={1}>{p.attachment_name ?? p.drive_file?.name}</Text>
              <Text style={styles.driveSub}>Open document</Text>
            </View>
            <Ionicons name="open-outline" size={18} color={colors.muted} />
          </Pressable>
        )}
        {p.version_history?.length > 0 && (
          <Text style={styles.history} testID="policy-version-history">
            Earlier versions: {p.version_history.map((v: any) => `v${v.version} (${formatDate(v.updated_at)})`).join(", ")}
          </Text>
        )}
      </ScrollView>
      {isAdmin && <AckTrackerSheet policyId={p.policy_id} visible={tracker} onClose={() => setTracker(false)} />}
      {isAdmin && <NewVersionSheet policy={p} visible={newVersion} onClose={() => setNewVersion(false)} />}
      <View style={[styles.footer, { paddingBottom: insets.bottom + 12 }]}>
        {p.acknowledged ? (
          <View style={styles.done} testID="policy-acknowledged">
            <Ionicons name="checkmark-circle" size={22} color={colors.successText} />
            <Text style={styles.doneText}>You have acknowledged this</Text>
          </View>
        ) : (
          <Button label={p.version > 1 ? "I have read the updated version" : "I have read and understood"} icon="checkmark" loading={saving} onPress={ack} testID="policy-acknowledge-button" />
        )}
      </View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  title: { fontSize: 26, fontWeight: "700", color: c.onSurface, letterSpacing: -0.5, marginTop: 12 },
  meta: { fontSize: 13, color: c.muted, marginTop: 6, marginBottom: 20 },
  body: { fontSize: 16, color: c.onSurfaceSecondary, lineHeight: 25 },
  driveCard: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 24, padding: 14, borderRadius: 14, backgroundColor: c.brandTertiary, minHeight: 56 },
  driveName: { fontSize: 15, fontWeight: "600", color: c.onSurface },
  driveSub: { fontSize: 12, color: c.muted },
  changeBox: { flexDirection: "row", gap: 8, alignItems: "center", backgroundColor: c.brandTertiary, borderRadius: 12, padding: 12, marginBottom: 16 },
  changeText: { flex: 1, fontSize: 14, color: c.onSurface, lineHeight: 20 },
  adminRow: { flexDirection: "row", gap: 8, marginBottom: 20 },
  history: { fontSize: 13, color: c.muted, marginTop: 16 },
  footer: { paddingHorizontal: 16, paddingTop: 12, borderTopWidth: 0.5, borderTopColor: c.divider, backgroundColor: c.surface },
  done: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 48, borderRadius: 12, backgroundColor: c.successSoft },
  doneText: { fontSize: 15, fontWeight: "600", color: c.successText },
}));
