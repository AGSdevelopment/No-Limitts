// Group task tracker (Compliance): who has / hasn't actioned or acknowledged each participant group task.
import { RefreshControl, ScrollView, View } from "react-native";
import { router } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Text } from "@/src/components/text";
import { Button, EmptyState, ErrorState, Loading, Pill, isoToDmy } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function GroupCompliance() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const q = useQuery<any>({ queryKey: ["groups-compliance"], queryFn: () => api("/participant-groups-compliance") });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as any)?.message ?? "Couldn't load group tasks."} onRetry={q.refetch} />;
  const d = q.data;
  return (
    <ScrollView style={styles.root} testID="groups-compliance" contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}>
      <View style={styles.summary}>
        <Text style={styles.big}>{d.outstanding}</Text>
        <Text style={styles.meta}>people still to action or acknowledge · {d.overdue} overdue task{d.overdue === 1 ? "" : "s"}</Text>
      </View>
      {!d.groups.length && <EmptyState icon="checkmark-done-outline" title="No group tasks yet" subtitle="Tasks given to participant groups are tracked here." />}
      {d.groups.map((g: any) => (
        <View key={g.group_id} style={{ gap: 8 }}>
          <Text style={styles.section}>{g.name}</Text>
          {g.tasks.map((t: any) => (
            <View key={t.task_group_id} style={styles.card} testID={`gc-task-${t.task_group_id}`}>
              <View style={styles.row}>
                <Text style={[styles.title, { flex: 1 }]}>{t.title}</Text>
                <Pill label={t.complete ? "Complete" : t.overdue ? "Overdue" : `${t.done.length}/${t.done.length + t.outstanding.length}`}
                  tone={t.complete ? "brand" : t.overdue ? "accent" : "muted"} />
              </View>
              <Text style={styles.meta}>{t.kind === "acknowledge" ? "Acknowledge" : "Action"}{t.due_date ? ` · due ${isoToDmy(t.due_date)}` : ""} · from {t.created_by}</Text>
              {!!t.done.length && <Text style={styles.body}>✓ {t.done.map((x: any) => x.name).join(", ")}</Text>}
              {!!t.outstanding.length && <Text style={[styles.body, { color: t.overdue ? colors.errorText : colors.warningText }]}>Waiting on: {t.outstanding.map((x: any) => x.name).join(", ")}</Text>}
            </View>
          ))}
          <Button label="Open group" variant="ghost" icon="people-outline" onPress={() => router.push(`/participant-groups/${g.group_id}`)} testID={`gc-open-${g.group_id}`} />
        </View>
      ))}
    </ScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  summary: { backgroundColor: c.brandTertiary, borderRadius: 14, padding: 14, gap: 4 },
  big: { fontSize: 28, fontWeight: "800", color: c.onSurface },
  card: { backgroundColor: c.surface, borderRadius: 14, padding: 12, gap: 4 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  section: { fontSize: 13, fontWeight: "700", color: c.muted, textTransform: "uppercase" },
  title: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  body: { fontSize: 14, color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
}));
