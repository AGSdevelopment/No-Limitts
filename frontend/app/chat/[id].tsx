import { useEffect, useRef, useState } from "react";
import { FlatList, Pressable, Text, TextInput, View } from "react-native";
import { Stack, useLocalSearchParams } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Avatar, EmptyState, ErrorState, Ionicons, Loading, tap } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function ChatThread() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const listRef = useRef<FlatList>(null);
  const q = useQuery<any[]>({ queryKey: ["messages", id], queryFn: () => api(`/conversations/${id}/messages`), refetchInterval: 3000 });
  const msgs = q.data ?? [];
  const lastId = msgs[msgs.length - 1]?.message_id;

  useEffect(() => {
    api(`/conversations/${id}/read`, { method: "POST" })
      .then(() => qc.invalidateQueries({ queryKey: ["conversations"] }))
      .catch(() => {});
  }, [id, lastId, qc]);

  const send = async () => {
    const t = text.trim();
    if (!t || sending) return;
    tap();
    setSending(true);
    try {
      const m = await api(`/conversations/${id}/messages`, { method: "POST", body: { text: t } });
      setText("");
      qc.setQueryData(["messages", id], (old: any[] = []) => [...old, m]);
      qc.invalidateQueries({ queryKey: ["conversations"] });
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSending(false);
    }
  };

  return (
    <View style={styles.root} testID="chat-thread-screen">
      <Stack.Screen options={{ title: name ?? "Chat" }} />
      <KeyboardAvoidingView behavior="padding" style={{ flex: 1 }} keyboardVerticalOffset={0}>
        {q.isLoading ? (
          <Loading />
        ) : q.isError ? (
          <ErrorState message="Failed to load messages." onRetry={() => q.refetch()} />
        ) : (
          <FlatList
            ref={listRef}
            data={msgs}
            keyExtractor={(m) => m.message_id}
            contentContainerStyle={{ padding: 16, gap: 10, flexGrow: 1 }}
            onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
            keyboardDismissMode="interactive"
            ListEmptyComponent={<EmptyState icon="chatbubble-ellipses-outline" title="No messages yet." subtitle="Start the conversation." />}
            renderItem={({ item, index }) => {
              const mine = item.sender_id === user?.user_id;
              const showName = !mine && msgs[index - 1]?.sender_id !== item.sender_id;
              return (
                <View style={[styles.msgRow, mine && { justifyContent: "flex-end" }]} testID={`message-${item.message_id}`}>
                  {!mine && (
                    <View style={{ width: 32 }}>{showName && <Avatar name={item.sender_name} picture={item.sender_picture} size={32} />}</View>
                  )}
                  <View style={{ maxWidth: "78%" }}>
                    {showName && <Text style={styles.sender}>{item.sender_name}</Text>}
                    <View style={[styles.bubble, mine ? styles.mine : styles.theirs]}>
                      <Text style={[styles.msgText, { color: mine ? colors.onBrandPrimary : colors.onSurface }]}>{item.text}</Text>
                    </View>
                    <Text style={[styles.time, mine && { textAlign: "right" }]}>
                      {new Date(item.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </Text>
                  </View>
                </View>
              );
            }}
          />
        )}
        <View style={[styles.composer, { paddingBottom: insets.bottom + 8 }]}>
          <TextInput
            testID="chat-message-input"
            value={text}
            onChangeText={setText}
            placeholder="Message"
            placeholderTextColor={colors.muted}
            style={styles.input}
            multiline
            maxLength={4000}
          />
          <Pressable
            testID="chat-send-button"
            onPress={send}
            disabled={!text.trim() || sending}
            style={[styles.send, (!text.trim() || sending) && { opacity: 0.4 }]}
          >
            <Ionicons name="arrow-up" size={20} color={colors.onBrandPrimary} />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  msgRow: { flexDirection: "row", alignItems: "flex-end", gap: 8 },
  sender: { fontSize: 12, fontWeight: "600", color: c.muted, marginBottom: 4, marginLeft: 4 },
  bubble: { paddingHorizontal: 14, paddingVertical: 10, borderRadius: 18 },
  mine: { backgroundColor: c.brandPrimary, borderBottomRightRadius: 6 },
  theirs: { backgroundColor: c.surfaceSecondary, borderBottomLeftRadius: 6 },
  msgText: { fontSize: 16, lineHeight: 21 },
  time: { fontSize: 11, color: c.muted, marginTop: 3, marginHorizontal: 4 },
  composer: { flexDirection: "row", alignItems: "flex-end", gap: 8, paddingHorizontal: 12, paddingTop: 8, borderTopWidth: 0.5, borderTopColor: c.divider, backgroundColor: c.surface },
  input: { flex: 1, minHeight: 40, maxHeight: 120, borderRadius: 20, backgroundColor: c.surfaceSecondary, paddingHorizontal: 16, paddingTop: 10, paddingBottom: 10, fontSize: 16, color: c.onSurface },
  send: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandPrimary, alignItems: "center", justifyContent: "center" },
}));
