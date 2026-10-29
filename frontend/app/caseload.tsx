// Service & Support Coordinators: their participants and recent case notes (from the Jotform Coordinator Case Note Form).
import { useState } from "react";
import { FlatList, Pressable, RefreshControl, View } from "react-native";
import { Text, TextInput } from "@/src/components/text";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, EmptyState, ErrorState, Ionicons, Loading, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const CASE_NOTE_FORM = "https://nolimitts.jotform.com/262772090420048";

export default function Caseload() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const [refreshing, setRefreshing] = useState(false);
  const { user } = useAuth();
  const allowed = user?.role === "admin" || ["support_coordinator", "hr"].includes(user?.user_type ?? "");
  const q = useQuery<any>({ queryKey: ["caseload"], queryFn: () => api("/caseload"), enabled: allowed });
  const [open, setOpen] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const toast = useToast();
  const [summaries, setSummaries] = useState<Record<string, string>>({});
  const [summarising, setSummarising] = useState<string | null>(null);

  const summarise = async (name: string) => {
    setSummarising(name);
    try {
      const r = await api<any>("/caseload/summary", { method: "POST", body: { name } });
      setSummaries((s) => ({ ...s, [name]: r.summary }));
    } catch (e: any) {
      toast(e.message ?? "Couldn't summarise right now", "error");
    } finally {
      setSummarising(null);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    try {
      await api("/caseload?refresh=true");
      q.refetch();
    } finally {
      setRefreshing(false);
    }
  };

  if (!allowed) return <EmptyState icon="lock-closed-outline" title="Not available" subtitle="The caseload is for Service & Support Coordinators and HR." />;

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as any)?.message ?? "Couldn't load your caseload"} onRetry={q.refetch} />;
  const people = (q.data.participants ?? []).filter((p: any) => p.name.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <FlatList
      style={styles.root}
      testID="caseload-screen"
      data={people}
      keyExtractor={(p) => p.name}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.brandPrimary} />}
      ListHeaderComponent={
        <View style={{ gap: 10 }}>
          <Pressable onPress={() => openLink(CASE_NOTE_FORM)} style={styles.newNote} testID="caseload-new-note">
            <Ionicons name="create-outline" size={20} color={colors.onBrandPrimary} />
            <Text style={styles.newNoteText}>Write a case note</Text>
          </Pressable>
          {q.data.configured && (
            <TextInput value={search} onChangeText={setSearch} placeholder="Search participants" placeholderTextColor={colors.muted}
              style={styles.search} testID="caseload-search" />
          )}
        </View>
      }
      ListEmptyComponent={
        !q.data.configured ? (
          <EmptyState icon="link-outline" title="Waiting for Jotform" subtitle="Case notes will appear here once your admin connects the Jotform account." />
        ) : (
          <EmptyState icon="people-outline" title="No participants yet" subtitle="Participants appear here once you submit a Coordinator Case Note for them. Pull down to refresh." />
        )
      }
      renderItem={({ item }) => {
        const expanded = open === item.name;
        return (
          <View style={styles.card} testID={`caseload-participant-${item.name}`}>
            <Pressable onPress={() => setOpen(expanded ? null : item.name)} style={styles.head} accessibilityLabel={`${item.name}, ${item.count} notes`}>
              <Avatar name={item.name} size={44} />
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.name}</Text>
                <Text style={styles.meta}>{item.count} note{item.count > 1 ? "s" : ""} · last {formatDate(item.last_date)}</Text>
              </View>
              <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={20} color={colors.muted} />
            </Pressable>
            {expanded && (
              <View style={styles.aiBox} testID={`caseload-summary-box-${item.name}`}>
                {summaries[item.name] ? (
                  <>
                    <View style={styles.aiHead}>
                      <Ionicons name="sparkles" size={16} color={colors.brandPrimary} />
                      <Text style={styles.aiTitle}>AI summary</Text>
                      <Pressable onPress={() => summarise(item.name)} hitSlop={10} style={styles.aiRedo} testID={`caseload-summary-refresh-${item.name}`}>
                        <Ionicons name="refresh" size={18} color={colors.brandPrimary} />
                      </Pressable>
                    </View>
                    <Text style={styles.field} testID={`caseload-summary-text-${item.name}`}>{summaries[item.name]}</Text>
                    <Text style={styles.aiNote}>AI can make mistakes. Check the notes below before acting.</Text>
                  </>
                ) : (
                  <Button label={summarising === item.name ? "Summarising…" : "Summarise with AI"} icon="sparkles-outline" variant="secondary"
                    loading={summarising === item.name} onPress={() => summarise(item.name)} testID={`caseload-summarise-${item.name}`} />
                )}
              </View>
            )}
            {expanded && item.notes.map((n: any) => (
              <View key={n.id} style={styles.note} testID={`caseload-note-${n.id}`}>
                <Text style={styles.noteDate}>{formatDate(n.date)}{n.coordinator ? ` · ${n.coordinator}` : ""}</Text>
                {n.fields.slice(0, 8).map((f: any, i: number) => (
                  <Text key={i} style={styles.field}><Text style={styles.fieldLabel}>{f.label}: </Text>{f.value}</Text>
                ))}
              </View>
            ))}
          </View>
        );
      }}
    />
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  newNote: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 48, borderRadius: 14, backgroundColor: c.brandPrimary },
  newNoteText: { fontSize: 15, fontWeight: "700", color: c.onBrandPrimary },
  search: { minHeight: 44, borderRadius: 12, backgroundColor: c.surface, paddingHorizontal: 14, fontSize: 15, color: c.onSurface, borderWidth: 1, borderColor: c.border },
  card: { backgroundColor: c.surface, borderRadius: 14, padding: 14, gap: 10 },
  head: { flexDirection: "row", alignItems: "center", gap: 12, minHeight: 48 },
  name: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted },
  note: { backgroundColor: c.surfaceSecondary, borderRadius: 12, padding: 12, gap: 4 },
  noteDate: { fontSize: 13, fontWeight: "700", color: c.brandPrimary },
  field: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
  fieldLabel: { fontWeight: "700", color: c.onSurfaceSecondary },
  aiBox: { backgroundColor: c.brandTertiary, borderRadius: 12, padding: 12, gap: 6 },
  aiHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  aiTitle: { flex: 1, fontSize: 14, fontWeight: "700", color: c.brandPrimary },
  aiRedo: { width: 44, height: 32, alignItems: "flex-end", justifyContent: "center" },
  aiNote: { fontSize: 12, color: c.muted },
}));
