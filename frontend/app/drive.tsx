import { useState } from "react";
import { FlatList, Pressable, RefreshControl, ScrollView, View } from "react-native";
import { Text, TextInput } from "@/src/components/text";
import { Stack, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openDriveFile } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { EmptyState, ErrorState, IconName, Ionicons, Loading, timeAgo } from "@/src/components/ui";
import { CATEGORIES, CAT_ICON } from "@/src/directory";
import { makeStyles, useTheme } from "@/src/theme";

type Item = { id: string; name: string; mime_type: string; is_folder: boolean; modified: string; size: number | null; pinned?: boolean };
type Listing = { root_id: string; root_name: string; folder_id: string; items: Item[]; pinned: Item[] };
type Crumb = { id: string; name: string };
type Space = "therapist" | "participant";
const SPACES: { key: Space; label: string; icon: IconName }[] = [
  { key: "therapist", label: "Therapist", icon: "medkit-outline" },
  { key: "participant", label: "Participants", icon: "people-outline" },
];

function iconFor(i: Item): IconName {
  if (i.is_folder) return "folder";
  const m = i.mime_type;
  if (m.includes("pdf")) return "document-text";
  if (m.includes("image")) return "image";
  if (m.includes("spreadsheet") || m.includes("excel") || m.includes("csv")) return "grid";
  if (m.includes("presentation") || m.includes("powerpoint")) return "easel";
  if (m.includes("video")) return "videocam";
  return "document";
}

function sizeLabel(n: number | null) {
  if (!n) return "";
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export default function CompanyDrive() {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const router = useRouter();
  const [path, setPath] = useState<Crumb[]>([]);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [opening, setOpening] = useState<string | null>(null);
  const [space, setSpace] = useState<Space>("therapist");
  const folder = path[path.length - 1]?.id ?? "";
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const qc = useQueryClient();

  const q = useQuery<Listing>({
    queryKey: ["drive-shared", space, folder, query],
    queryFn: () => api(`/drive/shared?space=${space}&folder=${encodeURIComponent(folder)}&q=${encodeURIComponent(query)}`),
    retry: false,
  });
  const data = q.data;

  const switchSpace = (s: Space) => {
    if (s === space) return;
    setSpace(s);
    setPath([]);
    setSearch("");
    setQuery("");
  };
  const spaceTabs = (
    <>
    {isAdmin && (
      <Stack.Screen
        options={{
          headerRight: () => (
            <Pressable testID="drive-add-button" onPress={() => router.push({ pathname: "/directory-new", params: { space } })} hitSlop={10} style={styles.addBtn} accessibilityLabel="Add to Company Drive">
              <Ionicons name="add-circle" size={24} color={colors.brandPrimary} />
              <Text style={styles.addText}>Add</Text>
            </Pressable>
          ),
        }}
      />
    )}
    <View style={styles.spaceRow} testID="drive-space-switch">
      {SPACES.map((s) => (
        <Pressable
          key={s.key}
          testID={`drive-space-${s.key}`}
          onPress={() => switchSpace(s.key)}
          style={[styles.spaceBtn, space === s.key && styles.spaceBtnOn]}
        >
          <Ionicons name={s.icon} size={18} color={space === s.key ? colors.onBrandPrimary : colors.brandPrimary} />
          <Text style={[styles.spaceText, space === s.key && { color: colors.onBrandPrimary }]} numberOfLines={1}>{s.label}</Text>
        </Pressable>
      ))}
    </View>
    <View style={styles.catRow} testID="drive-categories">
      {CATEGORIES[space].map((c) => (
        <Pressable key={c} testID={`drive-cat-${space}-${c}`} onPress={() => router.push({ pathname: "/directory", params: { space, category: c } })} style={styles.catBtn}>
          <Ionicons name={CAT_ICON[c] ?? "folder-outline"} size={16} color={colors.brandPrimary} />
          <Text style={styles.catText} numberOfLines={3}>{c}</Text>
        </Pressable>
      ))}
    </View>
    <View style={styles.spaceRow}>
      <Pressable testID="drive-places-button" onPress={() => router.push("/places")} style={[styles.spaceBtn, { flex: 1 }]}>
        <Ionicons name="star-outline" size={18} color={colors.brandPrimary} />
        <Text style={styles.spaceText} numberOfLines={1}>No Limitts favourites</Text>
      </Pressable>
    </View>
    </>
  );

  const togglePin = async (item: Item) => {
    try {
      if (item.pinned) await api(`/drive/pins/${item.id}`, { method: "DELETE" });
      else await api("/drive/pins", { method: "POST", body: { file_id: item.id, space } });
      await qc.invalidateQueries({ queryKey: ["drive-shared"] });
      toast(item.pinned ? "Unpinned" : "Pinned to the top of Company Drive", item.pinned ? "info" : "success");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const open = async (item: Item, fromPin = false) => {
    if (item.is_folder) {
      setSearch("");
      setQuery("");
      setPath((p) => (fromPin ? [{ id: item.id, name: item.name }] : [...p, { id: item.id, name: item.name }]));
      return;
    }
    setOpening(item.id);
    try {
      await openDriveFile(item.id, space);
    } catch {
      toast("Couldn't open this file", "error");
    } finally {
      setOpening(null);
    }
  };

  if (q.isLoading && !q.data) return <View style={styles.root}>{spaceTabs}<Loading /></View>;
  if (q.isError) {
    const notSet = (q.error as any)?.status === 409;
    const label = `${SPACES.find((s) => s.key === space)!.label} Resources`;
    return (
      <View style={styles.root} testID="drive-screen">
        {spaceTabs}
        {notSet ? (
          <EmptyState icon="folder-open-outline" title={`${label} isn't set up yet`} subtitle="An admin can choose this folder in Integrations." testID="drive-not-setup" />
        ) : (
          <ErrorState message={(q.error as any)?.message ?? "Couldn't load files."} onRetry={() => q.refetch()} />
        )}
      </View>
    );
  }
  const crumbs: Crumb[] = [{ id: "", name: data!.root_name }, ...path];
  const showPinned = !folder && !query && (data!.pinned?.length ?? 0) > 0;

  const renderRow = (item: Item, prefix = "drive-item") => (
    <Pressable
      key={`${prefix}-${item.id}`}
      testID={`${prefix}-${item.id}`}
      onPress={() => open(item, prefix === "drive-pinned")}
      style={({ pressed }) => [styles.item, pressed && { opacity: 0.7 }]}
    >
      <View style={[styles.iconBox, item.is_folder && { backgroundColor: colors.brandTertiary }]}>
        <Ionicons name={iconFor(item)} size={22} color={item.is_folder ? colors.brandPrimary : colors.accent} />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={styles.name} numberOfLines={2}>{item.name}</Text>
        <Text style={styles.meta}>
          {item.is_folder ? "Folder" : [sizeLabel(item.size), item.modified ? `Updated ${timeAgo(item.modified)}` : ""].filter(Boolean).join(" · ") || "File"}
        </Text>
      </View>
      {isAdmin && (
        <Pressable testID={`drive-pin-${item.id}`} onPress={() => togglePin(item)} hitSlop={6} style={styles.pinBtn}>
          <Ionicons name={item.pinned ? "pin" : "pin-outline"} size={20} color={item.pinned ? colors.accent : colors.muted} />
        </Pressable>
      )}
      {opening === item.id ? (
        <Text style={styles.meta}>Opening…</Text>
      ) : (
        <Ionicons name={item.is_folder ? "chevron-forward" : "open-outline"} size={18} color={colors.muted} />
      )}
    </Pressable>
  );

  return (
    <View style={styles.root} testID="drive-screen">
      {spaceTabs}
      <View style={styles.top}>
        <View style={styles.searchBox}>
          <Ionicons name="search" size={18} color={colors.muted} />
          <TextInput
            testID="drive-search-input"
            value={search}
            onChangeText={(t) => {
              setSearch(t);
              if (!t) setQuery("");
            }}
            onSubmitEditing={() => setQuery(search.trim())}
            returnKeyType="search"
            placeholder="Search files"
            placeholderTextColor={colors.muted}
            style={styles.searchInput}
          />
          {!!search && (
            <Pressable onPress={() => { setSearch(""); setQuery(""); }} hitSlop={10} testID="drive-search-clear">
              <Ionicons name="close-circle" size={18} color={colors.muted} />
            </Pressable>
          )}
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.crumbs}>
          {crumbs.map((c, i) => (
            <View key={c.id || "root"} style={styles.crumbRow}>
              {i > 0 && <Ionicons name="chevron-forward" size={14} color={colors.muted} />}
              <Pressable
                testID={`drive-crumb-${i}`}
                onPress={() => { setSearch(""); setQuery(""); setPath(path.slice(0, i)); }}
                style={styles.crumb}
                disabled={i === crumbs.length - 1}
              >
                <Text style={[styles.crumbText, i === crumbs.length - 1 && styles.crumbActive]} numberOfLines={1}>{c.name}</Text>
              </Pressable>
            </View>
          ))}
        </ScrollView>
      </View>
      <FlatList
        data={data!.items}
        keyExtractor={(i) => i.id}
        contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
        keyboardShouldPersistTaps="handled"
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
        ListHeaderComponent={
          showPinned ? (
            <View style={{ gap: 8, marginBottom: 16 }} testID="drive-pinned-section">
              <Text style={styles.section}>Pinned</Text>
              {data!.pinned.map((p) => renderRow(p, "drive-pinned"))}
              <Text style={[styles.section, { marginTop: 8 }]}>All files</Text>
            </View>
          ) : null
        }
        ListEmptyComponent={
          <EmptyState icon="folder-open-outline" title={query ? "No matching files" : "This folder is empty"} subtitle={query ? "Try a different search." : undefined} testID="drive-empty" />
        }
        ItemSeparatorComponent={() => <View style={{ height: 8 }} />}
        renderItem={({ item }) => renderRow(item)}
      />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  spaceRow: { flexDirection: "row", gap: 8, paddingHorizontal: 16, paddingTop: 12, paddingBottom: 4, backgroundColor: c.background },
  spaceBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 48, borderRadius: 12, borderWidth: 1.5, borderColor: c.brandPrimary, paddingHorizontal: 8 },
  spaceBtnOn: { backgroundColor: c.brandPrimary },
  spaceText: { fontSize: 14, fontWeight: "700", color: c.brandPrimary, flexShrink: 1 },
  top: { backgroundColor: c.background, paddingHorizontal: 16, paddingTop: 12, paddingBottom: 4, borderBottomWidth: 0.5, borderBottomColor: c.divider },
  searchBox: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 44, borderRadius: 12, backgroundColor: c.surfaceSecondary, paddingHorizontal: 12 },
  searchInput: { flex: 1, fontSize: 16, color: c.onSurface, minHeight: 44 },
  crumbs: { alignItems: "center", paddingVertical: 4 },
  crumbRow: { flexDirection: "row", alignItems: "center" },
  crumb: { minHeight: 40, justifyContent: "center", paddingHorizontal: 6, maxWidth: 200 },
  crumbText: { fontSize: 14, color: c.brandPrimary, fontWeight: "600" },
  crumbActive: { color: c.onSurface },
  item: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 14, padding: 12, minHeight: 64 },
  iconBox: { width: 44, height: 44, borderRadius: 12, backgroundColor: c.surfaceSecondary, alignItems: "center", justifyContent: "center" },
  name: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted },
  section: { fontSize: 13, fontWeight: "600", color: c.muted, textTransform: "uppercase", marginLeft: 4 },
  pinBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  catRow: { flexDirection: "row", gap: 8, paddingHorizontal: 16, paddingTop: 8, backgroundColor: c.background },
  catBtn: { flex: 1, alignItems: "center", justifyContent: "center", gap: 2, minHeight: 56, borderRadius: 12, backgroundColor: c.brandTertiary, paddingHorizontal: 4, paddingVertical: 6 },
  catText: { fontSize: 11, fontWeight: "700", color: c.brandPrimary, textAlign: "center" },
  addBtn: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 44, paddingHorizontal: 8 },
  addText: { fontSize: 15, fontWeight: "700", color: c.brandPrimary },
}));
