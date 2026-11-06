// Participant addresses used by the clock-in location check (Rosters and Service Coordinators).
import { useState } from "react";
import { FlatList, Pressable, RefreshControl, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Text } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Sheet } from "@/src/components/participant-sheets";
import { Button, EmptyState, ErrorState, Field, Ionicons, Loading, Pill } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function Addresses() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const q = useQuery<any[]>({ queryKey: ["pm-addresses"], queryFn: () => api("/pm/addresses") });
  const [open, setOpen] = useState<any>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as any)?.message ?? "Couldn't load participants."} onRetry={q.refetch} />;

  const save = async () => {
    setBusy(true);
    try {
      const r = await api<any>(`/participants/${open.participant_id}/address`, { method: "PUT", body: { address: text } });
      toast(!r.address ? "Address removed" : r.found ? "Address saved and found on the map" : "Saved, but we couldn't find it on the map. Check the spelling and postcode.",
        r.found || !r.address ? "success" : "info");
      setOpen(null);
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <FlatList
        style={styles.root}
        testID="addresses-screen"
        data={q.data ?? []}
        keyExtractor={(p) => p.participant_id}
        contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}
        ListHeaderComponent={<Text style={styles.meta}>Workers&apos; phones are checked against this address when they clock in. More than 300 m away, or no location shared, and Rosters review the times.</Text>}
        ListEmptyComponent={<EmptyState icon="home-outline" title="No participants yet" />}
        renderItem={({ item: p }) => (
          <Pressable onPress={() => { setOpen(p); setText(p.address); }} style={styles.card} testID={`address-${p.participant_id}`}>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.title}>{p.name}</Text>
              <Text style={styles.meta}>{p.address || "No address yet. Clock-ins aren't location checked."}</Text>
            </View>
            {!!p.address && <Pill label={p.found ? "On map" : "Not found"} tone={p.found ? "brand" : "accent"} />}
            <Ionicons name="create-outline" size={20} color={colors.muted} />
          </Pressable>
        )}
      />
      <Sheet visible={!!open} onClose={() => !busy && setOpen(null)} title={open?.name ?? ""} sub="Where supports usually happen (street, suburb, postcode)" testID="address-sheet">
        <Field label="Address" value={text} onChangeText={setText} placeholder="12 Example St, Joondalup WA 6027" testID="address-input" />
        <Button label="Save address" icon="location-outline" loading={busy} disabled={busy} onPress={save} testID="address-save" />
        <Button label="Cancel" variant="ghost" onPress={() => setOpen(null)} />
      </Sheet>
    </>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  card: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: c.surface, borderRadius: 14, padding: 14, minHeight: 56 },
  title: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
}));
