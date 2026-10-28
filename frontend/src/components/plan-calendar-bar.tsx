import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { useFocusEffect } from "expo-router";
import { useQuery } from "@tanstack/react-query";

import { api, openLink } from "@/src/api";
import { Ionicons } from "@/src/components/ui";
import { useToast } from "@/src/components/toast";
import { makeStyles, useTheme } from "@/src/theme";

// Plans pages: put plan end and review dates into the viewer's own Google Calendar, plus a test of the Monday email.
export function PlanCalendarBar({ page }: { page: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [busy, setBusy] = useState<"" | "cal" | "mail">("");
  const cal = useQuery<any>({
    queryKey: ["calendar-status"],
    queryFn: () => api("/integrations/google-calendar/status"),
    refetchInterval: (q) => (q.state.data?.connected ? false : 5000), // picks up a connection finished in the browser
  });
  useFocusEffect(
    useCallback(() => {
      cal.refetch();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []),
  );

  const run = async (kind: "cal" | "mail", fn: () => Promise<void>) => {
    setBusy(kind);
    try {
      await fn();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy("");
    }
  };
  const connect = () =>
    run("cal", async () => {
      const r = await api("/integrations/google-calendar/start", { method: "POST" });
      await openLink(r.authorization_url);
      cal.refetch();
    });
  const sync = () =>
    run("cal", async () => {
      const r = await api(`/agts-dashboard/calendar-sync?page=${encodeURIComponent(page)}`, { method: "POST" });
      toast(r.added || r.removed ? `Calendar updated: ${r.added} added, ${r.removed} removed` : "Your calendar is already up to date", "success");
    });
  const email = () =>
    run("mail", async () => {
      const r = await api(`/agts-dashboard/plans-email/test?page=${encodeURIComponent(page)}`, { method: "POST" });
      toast(r.sent ? `Summary emailed to ${r.to}` : "Nothing due this month, so no email was needed", "success");
    });

  const connected = !!cal.data?.connected;
  return (
    <View style={styles.bar} testID="plan-calendar-bar">
      {cal.data?.configured !== false && (
        <Pressable onPress={connected ? sync : connect} disabled={!!busy} style={({ pressed }) => [styles.btn, pressed && { opacity: 0.8 }]}
          accessibilityLabel={connected ? "Sync plan dates to my Google Calendar" : "Add plan dates to my Google Calendar"} testID="plan-calendar-btn">
          {busy === "cal" ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : <Ionicons name={connected ? "sync-outline" : "calendar-outline"} size={18} color={colors.brandPrimary} />}
          <Text style={styles.btnText} numberOfLines={1}>{connected ? "Sync calendar" : "Add to calendar"}</Text>
        </Pressable>
      )}
      <Pressable onPress={email} disabled={!!busy} style={({ pressed }) => [styles.btn, pressed && { opacity: 0.8 }]}
        accessibilityLabel="Email me this month's summary" testID="plan-email-btn">
        {busy === "mail" ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : <Ionicons name="mail-outline" size={18} color={colors.brandPrimary} />}
        <Text style={styles.btnText} numberOfLines={1}>Email summary</Text>
      </Pressable>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  bar: { flexDirection: "row", gap: 8, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  btn: { flex: 1, minHeight: 44, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingHorizontal: 10, borderRadius: 12, backgroundColor: c.brandSecondary },
  btnText: { color: c.onBrandSecondary, fontSize: 14, fontWeight: "600", flexShrink: 1 },
}));
