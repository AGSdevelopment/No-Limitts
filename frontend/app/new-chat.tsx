import { useState } from "react";
import { FlatList, Pressable, View } from "react-native";
import { Text, TextInput } from "@/src/components/text";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Avatar, EmptyState, ErrorState, Ionicons, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function NewChat() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const q = useQuery<any[]>({ queryKey: ["users"], queryFn: () => api("/users") });
  const people = (q.data ?? []).filter(
    (u) => u.user_id !== user?.user_id && `${u.name} ${u.email ?? ""} ${u.job_title ?? ""}`.toLowerCase().includes(search.toLowerCase()),
  );

  const open = async (u: any) => {
    try {
      const conv = await api("/dms", { method: "POST", body: { user_id: u.user_id } });
      router.replace({ pathname: "/chat/[id]", params: { id: conv.conversation_id, name: u.name } });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <View style={styles.root} testID="new-chat-screen">
      <View style={styles.searchWrap}>
        <Ionicons name="search" size={18} color={colors.muted} />
        <TextInput
          testID="new-chat-search-input"
          value={search}
          onChangeText={setSearch}
          placeholder="Search colleagues"
          placeholderTextColor={colors.muted}
          style={styles.search}
        />
      </View>
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Could not load colleagues." onRetry={() => q.refetch()} />
      ) : (
        <FlatList
          data={people}
          keyExtractor={(u) => u.user_id}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ paddingBottom: insets.bottom + 16, flexGrow: 1 }}
          ListEmptyComponent={<EmptyState icon="people-outline" title="No colleagues found" subtitle="Colleagues appear here once they sign in." />}
          renderItem={({ item }) => (
            <Pressable testID={`new-chat-user-${item.user_id}`} onPress={() => open(item)} style={({ pressed }) => [styles.row, pressed && { backgroundColor: colors.surfaceSecondary }]}>
              <Avatar name={item.name} picture={item.picture} size={44} />
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.name}</Text>
                {!!(item.email || item.job_title) && <Text style={styles.email}>{item.email || item.job_title}</Text>}
              </View>
              <Ionicons name="chatbubble-outline" size={20} color={colors.brandPrimary} />
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  searchWrap: { flexDirection: "row", alignItems: "center", gap: 8, margin: 16, paddingHorizontal: 12, height: 44, borderRadius: 12, backgroundColor: c.surfaceSecondary },
  search: { flex: 1, fontSize: 16, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 10, minHeight: 64 },
  name: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  email: { fontSize: 13, color: c.muted },
}));
