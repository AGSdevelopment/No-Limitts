import { useState } from "react";
import { FlatList, Pressable, RefreshControl, ScrollView, View } from "react-native";
import { Text } from "@/src/components/text";
import { Stack, useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Chip, EmptyState, ErrorState, IconBox, Ionicons, Loading, formatDate } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function Policies() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const [filter, setFilter] = useState<"All" | "Policy" | "Procedure" | "To review">("All");
  const q = useQuery<any[]>({ queryKey: ["policies"], queryFn: () => api("/policies") });
  const list = (q.data ?? []).filter((p) =>
    filter === "All" ? true : filter === "To review" ? !p.acknowledged : p.category === filter,
  );

  return (
    <View style={styles.root} testID="policies-screen">
      <Stack.Screen
        options={{
          headerRight:
            user?.role === "admin"
              ? () => (
                  <Pressable testID="policies-new-button" onPress={() => router.push("/compose?type=policy")} hitSlop={10}>
                    <Ionicons name="add-circle" size={30} color={colors.brandPrimary} style={{ marginRight: 8 }} />
                  </Pressable>
                )
              : undefined,
        }}
      />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow} contentContainerStyle={styles.chipContent}>
        {(["All", "To review", "Policy", "Procedure"] as const).map((f) => (
          <Chip key={f} label={f} selected={filter === f} onPress={() => setFilter(f)} testID={`policies-filter-${f.replace(" ", "-").toLowerCase()}`} />
        ))}
      </ScrollView>
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Could not load library." onRetry={() => q.refetch()} />
      ) : (
        <FlatList
          data={list}
          keyExtractor={(p) => p.policy_id}
          contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
          ListEmptyComponent={<EmptyState icon="shield-checkmark-outline" title={filter === "To review" ? "All policies reviewed" : "Library is empty."} />}
          renderItem={({ item }) => (
            <Pressable
              testID={`policy-${item.policy_id}`}
              onPress={() => router.push({ pathname: "/policy/[id]", params: { id: item.policy_id } })}
              style={({ pressed }) => [styles.row, pressed && { opacity: 0.8 }]}
            >
              <IconBox name={item.category === "Procedure" ? "list-outline" : "shield-checkmark-outline"} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.title} numberOfLines={2}>{item.title}</Text>
                <Text style={styles.sub}>{item.category} · {formatDate(item.created_at)}</Text>
              </View>
              {item.acknowledged ? (
                <Ionicons name="checkmark-circle" size={22} color={colors.success} />
              ) : (
                <View style={styles.newDot} />
              )}
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  chipRow: { flexGrow: 0, height: 56, backgroundColor: c.surface },
  chipContent: { paddingHorizontal: 16, gap: 8, alignItems: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 14, padding: 14, minHeight: 64 },
  title: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  newDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: c.accent },
}));
