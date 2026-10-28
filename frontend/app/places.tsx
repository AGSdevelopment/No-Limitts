import { useMemo, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, TextInput, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openLink } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, Chip, EmptyState, ErrorState, Field, Ionicons, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const KINDS = ["Eat", "Drink", "Eat & drink"];

export default function Places() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery<any[]>({ queryKey: ["places"], queryFn: () => api("/places") });
  const [filter, setFilter] = useState("All");
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ name: "", kind: "Eat & drink", address: "", link: "", note: "" });
  const [saving, setSaving] = useState(false);

  const list = useMemo(() => {
    const s = search.trim().toLowerCase();
    return (q.data ?? [])
      .filter((p) => filter === "All" || p.kind === filter || (p.kind === "Eat & drink" && filter !== "All"))
      .filter((p) => !s || `${p.name} ${p.address} ${p.note}`.toLowerCase().includes(s))
      .sort((a, b) => b.like_count - a.like_count || a.name.localeCompare(b.name));
  }, [q.data, filter, search]);

  const add = async () => {
    if (!f.name.trim()) return toast("Add the place's name", "error");
    setSaving(true);
    try {
      await api("/places", { method: "POST", body: f });
      toast(`${f.name.trim()} added. Thanks!`, "success");
      setF({ name: "", kind: "Eat & drink", address: "", link: "", note: "" });
      setAdding(false);
      qc.invalidateQueries({ queryKey: ["places"] });
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };
  const like = async (id: string) => {
    try {
      await api(`/places/${id}/like`, { method: "POST" });
      qc.invalidateQueries({ queryKey: ["places"] });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const remove = async (id: string) => {
    try {
      await api(`/places/${id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["places"] });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  if (adding) {
    return (
      <KeyboardAwareScrollView style={styles.root} contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 24 }} keyboardShouldPersistTaps="handled" bottomOffset={24} testID="places-add-screen">
        <Field label="Name" value={f.name} onChangeText={(v) => setF({ ...f, name: v })} placeholder="e.g. Little Willy's Cafe" testID="place-name-input" />
        <Text style={styles.label}>Type</Text>
        <View style={styles.chips}>
          {KINDS.map((k) => (
            <Chip key={k} label={k} selected={f.kind === k} onPress={() => setF({ ...f, kind: k })} testID={`place-kind-${k}`} />
          ))}
        </View>
        <Field label="Address or suburb" value={f.address} onChangeText={(v) => setF({ ...f, address: v })} placeholder="e.g. Fremantle" testID="place-address-input" />
        <Field label="Website or Google Maps link (optional)" value={f.link} onChangeText={(v) => setF({ ...f, link: v })} placeholder="https://" autoCapitalize="none" keyboardType="url" testID="place-link-input" />
        <Field label="Why we love it (optional)" value={f.note} onChangeText={(v) => setF({ ...f, note: v })} placeholder="e.g. Best flat white, great for team lunches" multiline testID="place-note-input" />
        <View style={{ flexDirection: "row", gap: 8 }}>
          <Button label="Cancel" variant="ghost" onPress={() => setAdding(false)} style={{ flex: 1 }} testID="place-cancel" />
          <Button label="Add place" icon="add" loading={saving} onPress={add} style={{ flex: 1 }} testID="place-save" />
        </View>
      </KeyboardAwareScrollView>
    );
  }

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load places." onRetry={() => q.refetch()} />;

  return (
    <FlatList
      style={styles.root}
      data={list}
      keyExtractor={(p) => p.place_id}
      contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} />}
      testID="places-screen"
      ListHeaderComponent={
        <View style={{ gap: 10, marginBottom: 4 }}>
          <Button label="Add a favourite place" icon="add-circle-outline" onPress={() => setAdding(true)} testID="places-add-button" />
          <TextInput value={search} onChangeText={setSearch} placeholder="Search places" placeholderTextColor={colors.muted} style={styles.search} testID="places-search" />
          <View style={styles.chips}>
            {["All", "Eat", "Drink"].map((k) => (
              <Chip key={k} label={k} selected={filter === k} onPress={() => setFilter(k)} testID={`places-filter-${k}`} />
            ))}
          </View>
        </View>
      }
      ListEmptyComponent={<EmptyState icon="restaurant-outline" title="No places yet" subtitle="Add the team's favourite spots to eat and drink." />}
      renderItem={({ item }) => (
        <View style={styles.card} testID={`place-${item.place_id}`}>
          <View style={styles.row}>
            <Ionicons name={item.kind === "Drink" ? "wine-outline" : item.kind === "Eat" ? "restaurant-outline" : "fast-food-outline"} size={22} color={colors.brandPrimary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.name}>{item.name}</Text>
              <Text style={styles.sub}>{[item.kind, item.address].filter(Boolean).join(" · ")}</Text>
            </View>
            <Pressable onPress={() => like(item.place_id)} style={styles.likeBtn} accessibilityLabel="Like" testID={`place-like-${item.place_id}`}>
              <Ionicons name={item.liked ? "heart" : "heart-outline"} size={22} color={item.liked ? colors.error : colors.muted} />
              <Text style={styles.sub}>{item.like_count}</Text>
            </Pressable>
          </View>
          {!!item.note && <Text style={styles.note}>{item.note}</Text>}
          <View style={styles.row}>
            <Text style={[styles.sub, { flex: 1 }]}>Added by {item.created_by}</Text>
            {!!item.link && (
              <Pressable onPress={() => openLink(item.link)} style={styles.linkBtn} testID={`place-open-${item.place_id}`}>
                <Text style={styles.link}>Open</Text>
              </Pressable>
            )}
            {item.can_delete && (
              <Pressable onPress={() => remove(item.place_id)} style={styles.likeBtn} accessibilityLabel="Remove place" testID={`place-delete-${item.place_id}`}>
                <Ionicons name="trash-outline" size={18} color={colors.muted} />
              </Pressable>
            )}
          </View>
        </View>
      )}
    />
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  label: { fontSize: 14, fontWeight: "600", color: c.onSurfaceSecondary, marginBottom: 8 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 8 },
  search: { minHeight: 44, borderRadius: 12, backgroundColor: c.surface, paddingHorizontal: 12, fontSize: 16, color: c.onSurface },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 14, gap: 8 },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  name: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  note: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
  likeBtn: { minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 4 },
  linkBtn: { minHeight: 44, paddingHorizontal: 12, justifyContent: "center" },
  link: { fontSize: 14, fontWeight: "700", color: c.brandPrimary },
}));
