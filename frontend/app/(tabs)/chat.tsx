import { useState } from "react";
import { FlatList, Pressable, RefreshControl, View } from "react-native";
import { Text } from "@/src/components/text";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { HeaderIcon, TabHeader } from "@/src/components/header";
import { Avatar, EmptyState, ErrorState, Ionicons, Loading, timeAgo, tap } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { makeStyles, useTheme } from "@/src/theme";

export default function ChatList() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const [seg, setSeg] = useState<"channel" | "dm">("channel");
  const q = useQuery<any[]>({ queryKey: ["conversations"], queryFn: () => api("/conversations"), refetchInterval: 5000 });
  const list = (q.data ?? []).filter((c) => c.type === seg);
  const unread = (t: string) => (q.data ?? []).filter((c) => c.type === t).reduce((s, c) => s + c.unread, 0);
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;

  return (
    <View style={styles.root} testID="chat-screen">
      <TabHeader title="Chat">
        {user?.role === "admin" && (
          <HeaderIcon icon="add" onPress={() => router.push("/compose?type=channel")} testID="chat-new-channel-button" />
        )}
        <HeaderIcon icon="create-outline" onPress={() => router.push("/new-chat")} testID="chat-new-dm-button" />
      </TabHeader>
      <View style={styles.segWrap}>
        <View style={styles.seg}>
          {(["channel", "dm"] as const).map((s) => (
            <Pressable
              key={s}
              testID={`chat-segment-${s}`}
              onPress={() => {
                tap();
                setSeg(s);
              }}
              style={[styles.segItem, seg === s && styles.segActive]}
            >
              <Text style={[styles.segText, seg === s && styles.segTextActive]}>{s === "channel" ? "Channels" : "Direct messages"}</Text>
              {unread(s) > 0 && <View style={styles.dot} />}
            </Pressable>
          ))}
        </View>
      </View>
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Failed to load chats." onRetry={() => q.refetch()} />
      ) : (
        <FlatList
          data={list}
          keyExtractor={(c) => c.conversation_id}
          contentContainerStyle={{ paddingBottom: bottomChrome + 24, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
          ListEmptyComponent={
            <EmptyState
              icon="chatbubbles-outline"
              title={seg === "dm" ? "No conversations yet" : "No channels yet"}
              subtitle="Start a conversation with a colleague."
              actionLabel={seg === "dm" ? "New message" : undefined}
              onAction={() => router.push("/new-chat")}
            />
          }
          renderItem={({ item }) => (
            <Pressable
              testID={`conversation-${item.conversation_id}`}
              onPress={() => router.push({ pathname: "/chat/[id]", params: { id: item.conversation_id, name: item.type === "channel" ? `#${item.name}` : item.name } })}
              style={({ pressed }) => [styles.row, pressed && { backgroundColor: colors.surfaceSecondary }]}
            >
              {item.type === "channel" ? (
                <View style={styles.hash}>
                  <Ionicons name="people" size={20} color={colors.onBrandTertiary} />
                </View>
              ) : (
                <Avatar name={item.name} picture={item.picture} size={48} />
              )}
              <View style={styles.rowBody}>
                <View style={styles.rowTop}>
                  <Text style={[styles.name, item.unread > 0 && { fontWeight: "700" }]} numberOfLines={1}>
                    {item.type === "channel" ? `#${item.name}` : item.name}
                  </Text>
                  {item.teams && <Ionicons name="logo-microsoft" size={13} color={colors.muted} testID={`conversation-teams-${item.conversation_id}`} />}
                  <Text style={styles.time}>{timeAgo(item.last_at)}</Text>
                </View>
                <View style={styles.rowTop}>
                  <Text style={styles.preview} numberOfLines={1}>
                    {item.last_message || item.description || "No messages yet"}
                  </Text>
                  {item.unread > 0 && (
                    <View style={styles.unread} testID={`conversation-unread-${item.conversation_id}`}>
                      <Text style={styles.unreadText}>{item.unread}</Text>
                    </View>
                  )}
                </View>
              </View>
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  segWrap: { paddingHorizontal: 16, paddingVertical: 12 },
  seg: { flexDirection: "row", backgroundColor: c.surfaceSecondary, borderRadius: 10, padding: 3 },
  segItem: { flex: 1, height: 36, borderRadius: 8, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 6 },
  segActive: { backgroundColor: c.surface, shadowColor: "#000", shadowOpacity: 0.08, shadowRadius: 4, shadowOffset: { width: 0, height: 1 }, elevation: 1 },
  segText: { fontSize: 14, fontWeight: "500", color: c.muted },
  segTextActive: { color: c.onSurface, fontWeight: "600" },
  dot: { width: 7, height: 7, borderRadius: 4, backgroundColor: c.accent },
  row: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 12, minHeight: 72 },
  hash: { width: 48, height: 48, borderRadius: 14, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  rowBody: { flex: 1, gap: 4, borderBottomWidth: 0.5, borderBottomColor: c.divider, paddingBottom: 12 },
  rowTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  name: { flex: 1, fontSize: 16, fontWeight: "600", color: c.onSurface },
  time: { fontSize: 12, color: c.muted },
  preview: { flex: 1, fontSize: 14, color: c.muted },
  unread: { minWidth: 20, height: 20, borderRadius: 10, backgroundColor: c.accent, alignItems: "center", justifyContent: "center", paddingHorizontal: 6 },
  unreadText: { color: c.onAccent, fontSize: 11, fontWeight: "700" },
}));
