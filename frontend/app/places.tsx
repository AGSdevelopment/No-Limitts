import { useMemo, useState } from "react";
import { useLocalSearchParams } from "expo-router";
import { useAuth } from "@/src/auth";
import { FlatList, Pressable, RefreshControl, View } from "react-native";
import { Text, TextInput } from "@/src/components/text";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openLink } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Button, Chip, ConfirmSheet, EmptyState, ErrorState, Field, Ionicons, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const KINDS = ["Eat & Drink", "Coffee", "WiFi / Meet"];
const KIND_ICON: Record<string, any> = { "Eat & Drink": "restaurant-outline", Coffee: "cafe-outline", "WiFi / Meet": "wifi-outline" };

export default function Places() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery<any[]>({ queryKey: ["places"], queryFn: () => api("/places") });
  const params = useLocalSearchParams<{ add?: string; kind?: string }>();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [filter, setFilter] = useState(params.kind && KINDS.includes(params.kind) ? params.kind : "All");
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(params.add === "1" && isAdmin);
  const [f, setF] = useState({ name: "", kind: params.kind && KINDS.includes(params.kind) ? params.kind : "Eat & Drink", address: "", link: "", note: "" });
  const [saving, setSaving] = useState(false);
  const [pick, setPick] = useState<any>(null);

  const pickLunch = () => {
    const pool = (q.data ?? []).filter((p) => p.kind === "Eat & Drink");
    if (!pool.length) return toast("No Eat & Drink favourites yet", "error");
    const others = pool.length > 1 ? pool.filter((p) => p.place_id !== pick?.place_id) : pool;
    setPick(others[Math.floor(Math.random() * others.length)]);
  };

  const list = useMemo(() => {
    const s = search.trim().toLowerCase();
    return (q.data ?? [])
      .filter((p) => filter === "All" || p.kind === filter)
      .filter((p) => !s || `${p.name} ${p.address} ${p.note}`.toLowerCase().includes(s))
      .sort((a, b) => b.like_count - a.like_count || a.name.localeCompare(b.name));
  }, [q.data, filter, search]);

  const [editing, setEditing] = useState<string | null>(null);
  const startEdit = (p: any) => {
    setF({ name: p.name, kind: p.kind, address: p.address, link: p.link, note: p.note });
    setEditing(p.place_id);
    setAdding(true);
  };
  const closeForm = () => {
    setAdding(false);
    setEditing(null);
    setF({ name: "", kind: "Eat & Drink", address: "", link: "", note: "" });
  };
  const add = async () => {
    if (!f.name.trim()) return toast("Add the place's name", "error");
    setSaving(true);
    try {
      if (editing) {
        await api(`/places/${editing}`, { method: "PUT", body: f });
        toast(`${f.name.trim()} updated`, "success");
      } else {
        await api("/places", { method: "POST", body: f });
        toast(`${f.name.trim()} added. Thanks!`, "success");
      }
      closeForm();
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
  const [removing, setRemoving] = useState<any>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const remove = async () => {
    setRemoveBusy(true);
    try {
      await api(`/places/${removing.place_id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["places"] });
      toast(`${removing.name} removed`, "info");
      setRemoving(null);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setRemoveBusy(false);
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
          <Button label="Cancel" variant="ghost" onPress={closeForm} style={{ flex: 1 }} testID="place-cancel" />
          <Button label={editing ? "Save" : "Add favourite"} icon={editing ? "checkmark" : "add"} loading={saving} onPress={add} style={{ flex: 1 }} testID="place-save" />
        </View>
      </KeyboardAwareScrollView>
    );
  }

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load places." onRetry={() => q.refetch()} />;

  return (
    <>
    <FlatList
      style={styles.root}
      data={list}
      keyExtractor={(p) => p.place_id}
      contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} />}
      testID="places-screen"
      ListHeaderComponent={
        <View style={{ gap: 10, marginBottom: 4 }}>
          {isAdmin && <Button label="Add a favourite" icon="add-circle-outline" onPress={() => setAdding(true)} testID="places-add-button" />}
          <Button label={pick ? "Pick again" : "Pick Friday lunch for us"} icon="shuffle" variant="secondary" onPress={pickLunch} testID="places-lunch-pick" />
          {pick && (
            <View style={styles.pickCard} testID="places-lunch-result">
              <Text style={styles.pickKicker}>🎉 Friday lunch is at</Text>
              <Text style={styles.pickName}>{pick.name}</Text>
              {!!pick.address && <Text style={styles.pickSub}>{pick.address}</Text>}
              {!!pick.note && <Text style={styles.pickSub}>{pick.note}</Text>}
              <View style={styles.row}>
                {!!pick.link && (
                  <Pressable onPress={() => openLink(pick.link)} style={styles.linkBtn} testID="places-lunch-open">
                    <Text style={styles.pickLink}>Open map/website</Text>
                  </Pressable>
                )}
                <Pressable onPress={() => setPick(null)} style={styles.linkBtn} testID="places-lunch-close">
                  <Text style={styles.pickLink}>Close</Text>
                </Pressable>
              </View>
            </View>
          )}
          <TextInput value={search} onChangeText={setSearch} placeholder="Search favourites" placeholderTextColor={colors.muted} style={styles.search} testID="places-search" />
          <View style={styles.chips}>
            {["All", ...KINDS].map((k) => (
              <Chip key={k} label={k} selected={filter === k} onPress={() => setFilter(k)} testID={`places-filter-${k}`} />
            ))}
          </View>
        </View>
      }
      ListEmptyComponent={<EmptyState icon="star-outline" title="No favourites yet" subtitle={isAdmin ? "Add the team's favourite spots to eat, grab a coffee or work and meet." : "Admins can add the team's favourite spots here."} />}
      renderItem={({ item }) => (
        <View style={styles.card} testID={`place-${item.place_id}`}>
          <View style={styles.row}>
            <Ionicons name={KIND_ICON[item.kind] ?? "star-outline"} size={22} color={colors.brandPrimary} />
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
              <Pressable onPress={() => startEdit(item)} style={styles.likeBtn} accessibilityLabel="Edit place" testID={`place-edit-${item.place_id}`}>
                <Ionicons name="create-outline" size={18} color={colors.muted} />
              </Pressable>
            )}
            {item.can_delete && (
              <Pressable onPress={() => setRemoving(item)} style={styles.likeBtn} accessibilityLabel="Remove place" testID={`place-delete-${item.place_id}`}>
                <Ionicons name="trash-outline" size={18} color={colors.muted} />
              </Pressable>
            )}
          </View>
        </View>
      )}
    />
    <ConfirmSheet
      visible={!!removing}
      title={`Remove ${removing?.name ?? ""}?`}
      message="This removes the favourite for everyone, including its likes."
      confirmLabel="Remove"
      loading={removeBusy}
      onConfirm={remove}
      onClose={() => setRemoving(null)}
    />
    </>
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
  pickCard: { backgroundColor: c.brandPrimary, borderRadius: 16, padding: 16, gap: 4 },
  pickKicker: { fontSize: 13, fontWeight: "600", color: c.onBrandPrimary, opacity: 0.9 },
  pickName: { fontSize: 22, fontWeight: "800", color: c.onBrandPrimary },
  pickSub: { fontSize: 14, color: c.onBrandPrimary, opacity: 0.9 },
  pickLink: { fontSize: 14, fontWeight: "700", color: c.onBrandPrimary, textDecorationLine: "underline" },
}));
