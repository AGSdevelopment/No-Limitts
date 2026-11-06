// Participant Management: entry to Funding (Finance / Rosters) and Rostering, plus Support Team tag approvals for coordinators.
import { Pressable, RefreshControl, ScrollView, View } from "react-native";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Text } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { EmptyState, IconBox, Ionicons, Loading, isoToDmy } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function ParticipantManagement() {
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const acc = useQuery<any>({ queryKey: ["pm-access"], queryFn: () => api("/pm/access") });
  const reqs = useQuery<any[]>({ queryKey: ["tag-requests"], queryFn: () => api("/support-team/requests"), enabled: !!acc.data?.coordinator });

  if (acc.isLoading) return <Loading />;
  const a = acc.data ?? {};
  if (!a.finance && !a.rosters && !a.worker && !a.coordinator) {
    return <EmptyState icon="lock-closed-outline" title="Not available" subtitle="Ask an Admin to give you Finance or Rosters access." />;
  }
  const decide = async (id: string, approve: boolean) => {
    try {
      await api(`/support-team/requests/${id}`, { method: "POST", body: { approve } });
      toast(approve ? "Added to the Support Team" : "Tag declined", "success");
      reqs.refetch();
      acc.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <ScrollView style={styles.root} contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
      refreshControl={<RefreshControl refreshing={acc.isRefetching} onRefresh={() => { acc.refetch(); reqs.refetch(); }} tintColor={colors.brandPrimary} />}
      testID="pm-screen">
      {(a.finance || a.rosters) && (
        <Option icon="wallet-outline" title="Funding" testID="pm-funding"
          sub={a.finance ? "Import funding, see budgets and update unit rates" : "See each participant's funding and what's left"}
          onPress={() => router.push("/pm/funding")} />
      )}
      <Option icon="calendar-outline" title="Rostering" testID="pm-rostering"
        sub={a.rosters ? `Roster shifts, approve clock times and run reports${a.awaiting_approval ? ` · ${a.awaiting_approval} to approve` : ""}` : "Your shifts, accept and clock in / out"}
        onPress={() => router.push("/pm/rostering")} />
      <Option icon="time-outline" title={a.finance || a.rosters ? "Timesheets" : "My hours"} testID="pm-timesheets"
        sub={a.finance || a.rosters ? "Approved hours per worker each week, Excel export" : "Your approved hours each week"}
        onPress={() => router.push("/pm/timesheets")} />
      {a.finance && (
        <Option icon="receipt-outline" title="Invoices" testID="pm-invoices" sub="Create GST-free invoices from completed shifts"
          onPress={() => router.push("/pm/invoices")} />
      )}
      {(a.rosters || a.coordinator) && (
        <Option icon="home-outline" title="Participant addresses" testID="pm-addresses" sub="Where clock-ins are location checked"
          onPress={() => router.push("/pm/addresses")} />
      )}

      {a.coordinator && (
        <View style={{ gap: 8 }}>
          <Text style={styles.section}>Support Team tags to approve</Text>
          {!reqs.data?.length && <Text style={styles.meta}>No tags waiting. Staff tag themselves to a participant in Team Directory.</Text>}
          {(reqs.data ?? []).map((r) => (
            <View key={r.request_id} style={styles.card} testID={`pm-tag-${r.request_id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.title}>{r.user_name} → {r.participant_name}</Text>
                <Text style={styles.meta}>Requested by {r.requested_by} · {isoToDmy(r.created_at.slice(0, 10))}</Text>
              </View>
              <Pressable onPress={() => decide(r.request_id, false)} style={styles.iconBtn} accessibilityLabel="Decline" testID={`pm-tag-decline-${r.request_id}`}>
                <Ionicons name="close-circle-outline" size={26} color={colors.errorText} />
              </Pressable>
              <Pressable onPress={() => decide(r.request_id, true)} style={styles.iconBtn} accessibilityLabel="Approve" testID={`pm-tag-approve-${r.request_id}`}>
                <Ionicons name="checkmark-circle" size={26} color={colors.successText} />
              </Pressable>
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

function Option({ icon, title, sub, onPress, testID }: { icon: any; title: string; sub: string; onPress: () => void; testID: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.option, pressed && { opacity: 0.85 }]} accessibilityRole="button" testID={testID}>
      <IconBox name={icon} size={48} />
      <View style={{ flex: 1 }}>
        <Text style={styles.optTitle}>{title}</Text>
        <Text style={styles.meta}>{sub}</Text>
      </View>
      <Ionicons name="chevron-forward" size={20} color={colors.muted} />
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  option: { flexDirection: "row", alignItems: "center", gap: 14, backgroundColor: c.surface, borderRadius: 16, padding: 16, borderWidth: 1, borderColor: c.brandPrimary },
  optTitle: { fontSize: 18, fontWeight: "800", color: c.onSurface },
  section: { fontSize: 13, fontWeight: "700", color: c.muted, textTransform: "uppercase", marginTop: 8 },
  card: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: c.surface, borderRadius: 14, padding: 12 },
  title: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
}));
