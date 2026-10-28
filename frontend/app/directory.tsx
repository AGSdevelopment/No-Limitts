import { useMemo, useState } from "react";
import { FlatList, Linking, Pressable, RefreshControl, Text, TextInput, View } from "react-native";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { ConfirmSheet, EmptyState, ErrorState, Ionicons, Loading } from "@/src/components/ui";
import { CAT_ICON, DirSpace, SPACE_LABEL } from "@/src/directory";
import { makeStyles, useTheme } from "@/src/theme";

export function openDirectoryFile(entryId: string, fileId: string) {
  return openLink(`${API_URL}/directory/${entryId}/files/${fileId}?token=${encodeURIComponent(getApiToken() ?? "")}`);
}

export default function Directory() {
  const { space, category } = useLocalSearchParams<{ space: DirSpace; category: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [removing, setRemoving] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const q = useQuery<any[]>({
    queryKey: ["directory", space, category],
    queryFn: () => api(`/directory?space=${space}&category=${encodeURIComponent(category)}`),
  });

  const list = useMemo(() => {
    const s = search.trim().toLowerCase();
    return (q.data ?? []).filter((e) => !s || `${e.name} ${e.contact} ${e.address} ${e.note}`.toLowerCase().includes(s));
  }, [q.data, search]);

  const remove = async () => {
    setBusy(true);
    try {
      await api(`/directory/${removing.entry_id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["directory", space, category] });
      toast(`${removing.name} removed`, "info");
      setRemoving(null);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const title = `${SPACE_LABEL[space] ?? ""} · ${category}`;

  return (
    <View style={styles.root} testID="directory-screen">
      <Stack.Screen
        options={{
          title,
          headerRight: isAdmin
            ? () => (
                <Pressable testID="directory-add-button" onPress={() => router.push({ pathname: "/directory-new", params: { space, category } })} hitSlop={10} style={styles.headerBtn} accessibilityLabel="Add">
                  <Ionicons name="add-circle" size={24} color={colors.brandPrimary} />
                  <Text style={styles.headerText}>Add</Text>
                </Pressable>
              )
            : undefined,
        }}
      />
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Couldn't load this list." onRetry={() => q.refetch()} />
      ) : (
        <FlatList
          data={list}
          keyExtractor={(e) => e.entry_id}
          contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
          ListHeaderComponent={
            (q.data?.length ?? 0) > 3 ? (
              <TextInput value={search} onChangeText={setSearch} placeholder={`Search ${category.toLowerCase()}`} placeholderTextColor={colors.muted} style={styles.search} testID="directory-search" />
            ) : null
          }
          ListEmptyComponent={
            <EmptyState
              icon={CAT_ICON[category] ?? "folder-open-outline"}
              title={search ? "No matches" : `No ${category.toLowerCase()} yet`}
              subtitle={search ? undefined : isAdmin ? "Tap Add to put the first one here." : "Admins can add entries here."}
              testID="directory-empty"
            />
          }
          renderItem={({ item }) => (
            <View style={styles.card} testID={`directory-entry-${item.entry_id}`}>
              <View style={styles.row}>
                <Ionicons name={CAT_ICON[category] ?? "folder-outline"} size={22} color={colors.brandPrimary} />
                <Text style={[styles.name, { flex: 1 }]}>{item.name}</Text>
                {isAdmin && (
                  <>
                    <Pressable onPress={() => router.push({ pathname: "/directory-new", params: { edit: item.entry_id } })} style={styles.iconBtn} accessibilityLabel="Edit" testID={`directory-edit-${item.entry_id}`}>
                      <Ionicons name="create-outline" size={20} color={colors.muted} />
                    </Pressable>
                    <Pressable onPress={() => setRemoving(item)} style={styles.iconBtn} accessibilityLabel="Remove" testID={`directory-delete-${item.entry_id}`}>
                      <Ionicons name="trash-outline" size={20} color={colors.muted} />
                    </Pressable>
                  </>
                )}
              </View>
              {!!item.contact && <Text style={styles.sub}>Contact: {item.contact}</Text>}
              {!!item.address && <Text style={styles.sub}>{item.address}</Text>}
              {!!item.note && <Text style={styles.note}>{item.note}</Text>}
              <View style={styles.actions}>
                {!!item.phone && <Action icon="call-outline" label={item.phone} onPress={() => Linking.openURL(`tel:${item.phone.replace(/\s/g, "")}`)} testID={`directory-phone-${item.entry_id}`} />}
                {!!item.email && <Action icon="mail-outline" label="Email" onPress={() => Linking.openURL(`mailto:${item.email}`)} testID={`directory-email-${item.entry_id}`} />}
                {!!item.link && <Action icon="open-outline" label="Website" onPress={() => openLink(item.link)} testID={`directory-link-${item.entry_id}`} />}
              </View>
              {item.files.map((f: any) => (
                <Pressable key={f.file_id} onPress={() => openDirectoryFile(item.entry_id, f.file_id)} style={styles.file} testID={`directory-file-${f.file_id}`}>
                  <Ionicons name="document-attach-outline" size={18} color={colors.accent} />
                  <Text style={styles.fileName} numberOfLines={1}>{f.name}</Text>
                  <Ionicons name="open-outline" size={16} color={colors.muted} />
                </Pressable>
              ))}
            </View>
          )}
        />
      )}
      <ConfirmSheet
        visible={!!removing}
        title={`Remove ${removing?.name ?? ""}?`}
        message="This removes the entry and its files for everyone."
        confirmLabel="Remove"
        loading={busy}
        onConfirm={remove}
        onClose={() => setRemoving(null)}
      />
    </View>
  );
}

function Action({ icon, label, onPress, testID }: { icon: any; label: string; onPress: () => void; testID: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <Pressable onPress={onPress} style={styles.action} testID={testID}>
      <Ionicons name={icon} size={16} color={colors.brandPrimary} />
      <Text style={styles.actionText} numberOfLines={1}>{label}</Text>
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  headerBtn: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 44, paddingHorizontal: 8 },
  headerText: { fontSize: 15, fontWeight: "700", color: c.brandPrimary },
  search: { minHeight: 44, borderRadius: 12, backgroundColor: c.surface, paddingHorizontal: 12, fontSize: 16, color: c.onSurface, marginBottom: 4 },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 14, gap: 6 },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  name: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  note: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  action: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 40, paddingHorizontal: 12, borderRadius: 20, backgroundColor: c.brandTertiary, maxWidth: 220 },
  actionText: { fontSize: 13, fontWeight: "600", color: c.brandPrimary, flexShrink: 1 },
  file: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 44, paddingHorizontal: 10, borderRadius: 10, backgroundColor: c.surfaceSecondary },
  fileName: { flex: 1, fontSize: 14, color: c.onSurface },
}));
