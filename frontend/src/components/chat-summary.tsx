import { useEffect, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Button, Ionicons } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Summary = { summary: string; message_count: number };

export function ChatSummarySheet({ convId, visible, onClose }: { convId: string; visible: boolean; onClose: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const [canRetry, setCanRetry] = useState(true);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setError("");
    setData(null);
    try {
      setData(await api<Summary>(`/conversations/${convId}/summary`, { method: "POST" }));
    } catch (e: any) {
      setError(e.message);
      setCanRetry(e.status !== 400);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (visible) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, convId]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.scrim} onPress={onClose} testID="chat-summary-backdrop" />
      <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID="chat-summary-sheet">
        <View style={styles.grabber} />
        <View style={styles.head}>
          <View style={styles.icon}>
            <Ionicons name="sparkles" size={16} color={colors.onBrandPrimary} />
          </View>
          <Text style={styles.title}>Chat summary</Text>
          <Pressable onPress={onClose} hitSlop={10} style={styles.close} testID="chat-summary-close">
            <Ionicons name="close" size={22} color={colors.muted} />
          </Pressable>
        </View>
        {loading ? (
          <View style={styles.center} testID="chat-summary-loading">
            <ActivityIndicator color={colors.brandPrimary} />
            <Text style={styles.sub}>Claude is reading the conversation…</Text>
          </View>
        ) : error ? (
          <View style={styles.center}>
            <Text style={styles.sub} testID="chat-summary-error">{error}</Text>
            {canRetry && <Button label="Try again" variant="secondary" onPress={load} testID="chat-summary-retry" />}
          </View>
        ) : data ? (
          <>
            <ScrollView style={{ maxHeight: 420 }} contentContainerStyle={{ paddingBottom: 8 }}>
              <Text style={styles.body} testID="chat-summary-text">{data.summary}</Text>
            </ScrollView>
            <Text style={styles.meta}>Based on the last {data.message_count} messages · powered by Claude</Text>
            <Button label="Refresh summary" variant="ghost" icon="refresh" onPress={load} testID="chat-summary-refresh" />
          </>
        ) : null}
      </View>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  scrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.35)" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, paddingHorizontal: 20, paddingTop: 8, gap: 12 },
  grabber: { alignSelf: "center", width: 40, height: 5, borderRadius: 3, backgroundColor: c.border, marginBottom: 4 },
  head: { flexDirection: "row", alignItems: "center", gap: 10 },
  icon: { width: 28, height: 28, borderRadius: 14, backgroundColor: c.brandPrimary, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, fontSize: 18, fontWeight: "700", color: c.onSurface },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  center: { alignItems: "center", gap: 12, paddingVertical: 32 },
  sub: { fontSize: 14, color: c.muted, textAlign: "center" },
  body: { fontSize: 16, lineHeight: 24, color: c.onSurface },
  meta: { fontSize: 12, color: c.muted },
}));
