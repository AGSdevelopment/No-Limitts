import { useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { Stack, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, Card, ConfirmSheet, EmptyState, ErrorState, Ionicons, Loading, Pill, timeAgo } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";
import { SocialPost } from "@/src/components/social-post";

export default function Updates() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [del, setDel] = useState<any>(null);
  const q = useQuery<any[]>({ queryKey: ["updates"], queryFn: () => api("/updates") });
  const isAdmin = user?.role === "admin";

  const remove = async () => {
    try {
      await api(`/updates/${del.update_id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["updates"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast("Update deleted");
    } catch (e: any) {
      toast(e.message, "error");
    }
    setDel(null);
  };

  return (
    <View style={styles.root} testID="updates-screen">
      <Stack.Screen
        options={{
          headerRight: isAdmin
            ? () => (
                <Pressable testID="updates-new-button" onPress={() => router.push("/compose?type=update")} hitSlop={10}>
                  <Ionicons name="add-circle" size={30} color={colors.brandPrimary} style={{ marginRight: 8 }} />
                </Pressable>
              )
            : undefined,
        }}
      />
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Could not load updates." onRetry={() => q.refetch()} />
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(u) => u.update_id}
          contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
          ListEmptyComponent={
            <EmptyState icon="megaphone-outline" title="No updates yet" actionLabel={isAdmin ? "Post update" : undefined} onAction={() => router.push("/compose?type=update")} />
          }
          renderItem={({ item }) =>
            item.source ? (
              <View>
                <SocialPost item={item} />
                {isAdmin && (
                  <Button label="Delete" variant="ghost" icon="trash-outline" onPress={() => setDel(item)} style={styles.del} testID={`update-delete-${item.update_id}`} />
                )}
              </View>
            ) : (
            <Card testID={`update-${item.update_id}`}>
              <View style={styles.meta}>
                {item.pinned && <Pill label="Pinned" tone="accent" />}
                <Text style={styles.sub}>{item.author_name} · {timeAgo(item.created_at)}</Text>
              </View>
              <Text style={styles.title}>{item.title}</Text>
              <Text style={styles.body}>{item.body}</Text>
              {isAdmin && (
                <Button label="Delete" variant="ghost" icon="trash-outline" onPress={() => setDel(item)} style={styles.del} testID={`update-delete-${item.update_id}`} />
              )}
            </Card>
            )
          }
        />
      )}
      <ConfirmSheet visible={!!del} title="Delete update?" message="This removes it for everyone." confirmLabel="Delete" onConfirm={remove} onClose={() => setDel(null)} />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  meta: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  sub: { fontSize: 13, color: c.muted },
  title: { fontSize: 18, fontWeight: "700", color: c.onSurface, marginBottom: 6 },
  body: { fontSize: 15, color: c.onSurfaceSecondary, lineHeight: 22 },
  del: { alignSelf: "flex-start", paddingHorizontal: 0, marginTop: 4, minHeight: 44 },
}));
