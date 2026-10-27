import { useState } from "react";
import { FlatList, Pressable, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { GroupPickerSheet } from "@/src/components/group-picker";
import { useToast } from "@/src/components/toast";
import { Avatar, EmptyState, ErrorState, Ionicons, Loading, Pill } from "@/src/components/ui";
import { groupLabel } from "@/src/groups";
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
  const [groupFor, setGroupFor] = useState<any>(null);
  const [groupSel, setGroupSel] = useState<string[]>([]);
  const [savingGroup, setSavingGroup] = useState(false);
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
  const saveGroup = async () => {
    if (!groupFor || savingGroup) return;
    setSavingGroup(true);
    try {
      await api(`/users/${groupFor.user_id}/group`, { method: "PATCH", body: { staff_group: groupSel[0] ?? null } });
      qc.invalidateQueries({ queryKey: ["users"] });
      qc.invalidateQueries({ queryKey: ["forms"] });
      toast(groupSel[0] ? `${groupFor.name}: ${groupLabel(groupSel[0])}` : `${groupFor.name}: no group`);
      setGroupFor(null);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSavingGroup(false);
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
                <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
                  <Pill label={item.role === "admin" ? "Admin" : "Employee"} tone={item.role === "admin" ? "brand" : "muted"} />
                  {!!item.staff_group && <Pill label={groupLabel(item.staff_group)} />}
                </View>
                {isAdmin && (
                  <View style={styles.actions}>
                    <Pressable
                      testID={`team-group-button-${item.user_id}`}
                      onPress={() => {
                        setGroupSel(item.staff_group ? [item.staff_group] : []);
                        setGroupFor(item);
                      }}
                      style={styles.smallBtn}
                    >
                      <Text style={styles.smallBtnText}>{item.staff_group ? "Change group" : "Set group"}</Text>
                    </Pressable>
                    {item.user_id !== user?.user_id && (
                      <Pressable testID={`team-role-toggle-${item.user_id}`} disabled={busy === item.user_id} onPress={() => toggleRole(item)} style={styles.smallBtn}>
                        <Text style={styles.smallBtnText}>{item.role === "admin" ? "Make employee" : "Make admin"}</Text>
                      </Pressable>
                    )}
                  </View>
                )}
              </View>
              {item.user_id !== user?.user_id && (
                <Pressable testID={`team-message-${item.user_id}`} onPress={() => message(item)} style={styles.iconBtn}>
                  <Ionicons name="chatbubble-outline" size={20} color={colors.brandPrimary} />
                </Pressable>
              )}
            </View>
          )}
        />
      )}
      <GroupPickerSheet
        visible={!!groupFor}
        title={`Staff group for ${groupFor?.name ?? ""}`}
        subtitle="Controls which forms they can see. Admins always see every form."
        multi={false}
        selected={groupSel}
        onChange={setGroupSel}
        onClose={() => setGroupFor(null)}
        onSave={saveGroup}
        saving={savingGroup}
        emptyLabel="No group"
        emptyHint="Sees only forms open to everyone"
      />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  row: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 14, padding: 14 },
  name: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  email: { fontSize: 13, color: c.muted },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  actions: { flexDirection: "row", gap: 8, flexWrap: "wrap", marginTop: 4 },
  smallBtn: { minHeight: 36, paddingHorizontal: 12, borderRadius: 18, backgroundColor: c.brandTertiary, justifyContent: "center" },
  smallBtnText: { fontSize: 13, fontWeight: "600", color: c.onBrandTertiary },
}));
