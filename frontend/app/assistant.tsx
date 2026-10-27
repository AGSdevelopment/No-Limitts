import { useRef, useState } from "react";
import { FlatList, Pressable, Text, TextInput, View } from "react-native";
import { Stack } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAvoidingView, useKeyboardState } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, streamAsk } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { IconBox, Ionicons, Loading, tap } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Msg = { message_id: string; role: "user" | "assistant"; text: string };

const SUGGESTIONS = [
  "What should I do if I'm injured at work?",
  "Which of my certificates expire soon?",
  "Summarise our health & safety policy",
];

export default function Assistant() {
  const insets = useSafeAreaInsets();
  const keyboardOpen = useKeyboardState((s) => s.isVisible);
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const listRef = useRef<FlatList>(null);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const q = useQuery<Msg[]>({ queryKey: ["ai-history"], queryFn: () => api("/ai/history") });
  const msgs = [...(q.data ?? []), ...pending];

  const ask = async (question: string) => {
    const t = question.trim();
    if (!t || busy) return;
    tap();
    setText("");
    setBusy(true);
    const answerId = `a-${Date.now()}`;
    setPending([
      { message_id: `q-${Date.now()}`, role: "user", text: t },
      { message_id: answerId, role: "assistant", text: "" },
    ]);
    try {
      await streamAsk(t, (d) =>
        setPending((p) => p.map((m) => (m.message_id === answerId ? { ...m, text: m.text + d } : m))),
      );
      await qc.invalidateQueries({ queryKey: ["ai-history"] });
      setPending([]);
    } catch (e: any) {
      toast(e.message, "error");
      setPending([]);
      qc.invalidateQueries({ queryKey: ["ai-history"] });
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    await api("/ai/history", { method: "DELETE" }).catch(() => {});
    qc.invalidateQueries({ queryKey: ["ai-history"] });
  };

  return (
    <View style={styles.root} testID="assistant-screen">
      <Stack.Screen
        options={{
          headerRight: msgs.length
            ? () => (
                <Pressable testID="assistant-clear-button" onPress={clear} hitSlop={10} style={{ marginRight: 8 }}>
                  <Text style={styles.clear}>Clear</Text>
                </Pressable>
              )
            : undefined,
        }}
      />
      <KeyboardAvoidingView behavior="translate-with-padding" style={{ flex: 1 }} automaticOffset>
        {q.isLoading ? (
          <Loading />
        ) : (
          <FlatList
            ref={listRef}
            data={msgs}
            keyExtractor={(m) => m.message_id}
            contentContainerStyle={{ padding: 16, gap: 12, flexGrow: 1 }}
            onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
            keyboardDismissMode="interactive"
            keyboardShouldPersistTaps="handled"
            ListEmptyComponent={
              <View style={styles.empty}>
                <IconBox name="sparkles" size={64} />
                <Text style={styles.emptyTitle}>Ask about company policies</Text>
                <Text style={styles.emptySub}>Answers come from your company&apos;s policies & procedures, powered by Claude.</Text>
                <View style={{ gap: 8, marginTop: 16, alignSelf: "stretch" }}>
                  {SUGGESTIONS.map((s, i) => (
                    <Pressable key={s} testID={`assistant-suggestion-${i}`} onPress={() => ask(s)} style={styles.suggestion}>
                      <Ionicons name="chatbubble-ellipses-outline" size={18} color={colors.brandPrimary} />
                      <Text style={styles.suggestionText}>{s}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            }
            renderItem={({ item }) => {
              const mine = item.role === "user";
              return (
                <View style={[styles.row, mine && { justifyContent: "flex-end" }]} testID={`assistant-msg-${item.role}`}>
                  {!mine && (
                    <View style={styles.aiAvatar}>
                      <Ionicons name="sparkles" size={14} color={colors.onBrandPrimary} />
                    </View>
                  )}
                  <View style={[styles.bubble, mine ? styles.mine : styles.theirs]}>
                    <Text style={[styles.msgText, { color: mine ? colors.onBrandPrimary : colors.onSurface }]}>
                      {item.text.replace(/\*\*/g, "") || "Thinking…"}
                    </Text>
                  </View>
                </View>
              );
            }}
          />
        )}
        <View style={[styles.composer, { paddingBottom: keyboardOpen ? 8 : insets.bottom + 8 }]}>
          <TextInput
            testID="assistant-input"
            value={text}
            onChangeText={setText}
            placeholder="Ask a question"
            placeholderTextColor={colors.muted}
            style={styles.input}
            multiline
            maxLength={2000}
          />
          <Pressable testID="assistant-send-button" onPress={() => ask(text)} disabled={!text.trim() || busy} style={[styles.send, (!text.trim() || busy) && { opacity: 0.4 }]}>
            <Ionicons name="arrow-up" size={20} color={colors.onBrandPrimary} />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  clear: { color: c.brandPrimary, fontWeight: "600", fontSize: 15 },
  empty: { flex: 1, alignItems: "center", justifyContent: "center", padding: 16, gap: 6 },
  emptyTitle: { fontSize: 18, fontWeight: "700", color: c.onSurface, marginTop: 12 },
  emptySub: { fontSize: 14, color: c.muted, textAlign: "center", lineHeight: 20 },
  suggestion: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14, borderRadius: 12, backgroundColor: c.brandTertiary, minHeight: 48 },
  suggestionText: { flex: 1, fontSize: 14, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "flex-end", gap: 8 },
  aiAvatar: { width: 28, height: 28, borderRadius: 14, backgroundColor: c.brandPrimary, alignItems: "center", justifyContent: "center" },
  bubble: { paddingHorizontal: 14, paddingVertical: 10, borderRadius: 18, maxWidth: "82%" },
  mine: { backgroundColor: c.brandPrimary, borderBottomRightRadius: 6 },
  theirs: { backgroundColor: c.surfaceSecondary, borderBottomLeftRadius: 6 },
  msgText: { fontSize: 16, lineHeight: 22 },
  composer: { flexDirection: "row", alignItems: "flex-end", gap: 8, paddingHorizontal: 12, paddingTop: 8, borderTopWidth: 0.5, borderTopColor: c.divider, backgroundColor: c.surface },
  input: { flex: 1, minHeight: 44, maxHeight: 120, borderRadius: 22, backgroundColor: c.surfaceSecondary, paddingHorizontal: 16, paddingTop: 12, paddingBottom: 12, fontSize: 16, color: c.onSurface },
  send: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandPrimary, alignItems: "center", justifyContent: "center" },
}));
