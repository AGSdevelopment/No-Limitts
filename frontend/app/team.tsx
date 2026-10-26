import { useState } from "react";
import { FlatList, Pressable, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, EmptyState, ErrorState, Ionicons, Loading, Pill } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function Team() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const q = useQuery<any[]>({ queryKey: ["users"], queryFn: () => api("/users") });
  const isAdmin = user?.role === "admin";

  const message = async (u: any) => {
    try {
      const conv = await api("/dms", { method: "POST", body: { user_id: u.user_id } });
      router.push({ pathname: "/chat/[id]", params: { id: conv.conversation_id, name: u.name } });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const toggleRole = async (u: any) => {
    setBusy(u.user_id);
    try {
      const role = u.role === "admin" ? "employee" : "admin";
      await api(`/users/${u.user_id}/role`, { method: "PATCH", body: { role } });
      qc.invalidateQueries({ queryKey: ["users"] });
      toast(`${u.name} is now ${role === "admin" ? "an admin" : "an employee"}`);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={styles.root} testID="team-screen">
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Could not load team." onRetry={() => q.refetch()} />
      ) : (
        <FlatList
          data={q.data}
          keyExtractor={(u) => u.user_id}
          contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          ListEmptyComponent={<EmptyState icon="people-outline" title="No one here yet" />}
          renderItem={({ item }) => (
            <View style={styles.row} testID={`team-member-${item.user_id}`}>
              <Avatar name={item.name} picture={item.picture} size={48} />
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={styles.name}>{item.name}{item.user_id === user?.user_id ? " (you)" : ""}</Text>
                <Text style={styles.email} numberOfLines={1}>{item.email}</Text>
                <Pill label={item.role === "admin" ? "Admin" : "Employee"} tone={item.role === "admin" ? "brand" : "muted"} />
              </View>
              <View style={{ gap: 6, alignItems: "flex-end" }}>
                {item.user_id !== user?.user_id && (
                  <Pressable testID={`team-message-${item.user_id}`} onPress={() => message(item)} style={styles.iconBtn}>
                    <Ionicons name="chatbubble-outline" size={20} color={colors.brandPrimary} />
                  </Pressable>
                )}
                {isAdmin && item.user_id !== user?.user_id && (
                  <Button
                    label={item.role === "admin" ? "Make employee" : "Make admin"}
                    variant="ghost"
                    loading={busy === item.user_id}
                    onPress={() => toggleRole(item)}
                    style={styles.roleBtn}
                    testID={`team-role-toggle-${item.user_id}`}
                  />
                )}
              </View>
            </View>
          )}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  row: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 14, padding: 14 },
  name: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  email: { fontSize: 13, color: c.muted },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  roleBtn: { minHeight: 36, paddingHorizontal: 4 },
}));
