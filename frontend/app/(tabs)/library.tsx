import { Pressable, ScrollView, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { TabHeader } from "@/src/components/header";
import { Avatar, Button, IconBox, IconName, Ionicons, Pill } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { makeStyles, useTheme } from "@/src/theme";

type Row = { icon: IconName; label: string; to: any; id: string; count?: number };

export default function Library() {
  const router = useRouter();
  const { user, signOut } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const dash = useQuery<any>({ queryKey: ["dashboard"], queryFn: () => api("/dashboard") });
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;
  const isAdmin = user?.role === "admin";

  const resources: Row[] = [
    { icon: "notifications-outline", label: "Notifications", to: "/notifications", id: "notifications", count: dash.data?.unread_notifications },
    { icon: "megaphone-outline", label: "Company updates", to: "/updates", id: "updates" },
    { icon: "checkbox-outline", label: "My tasks", to: "/tasks", id: "tasks", count: dash.data?.open_task_count },
    { icon: "clipboard-outline", label: "Forms", to: "/forms", id: "forms" },
    { icon: "school-outline", label: "CPD", to: "/cpd", id: "cpd" },
    { icon: "calendar-outline", label: "Events", to: "/events", id: "events" },
    { icon: "shield-checkmark-outline", label: "Policies & procedures", to: "/policies", id: "policies", count: dash.data?.pending_policies },
    { icon: "sparkles-outline", label: "Ask AI about policies", to: "/assistant", id: "assistant" },
    { icon: "people-outline", label: "Team directory", to: "/team", id: "team" },
    { icon: "folder-open-outline", label: "Company Drive", to: "/drive", id: "drive" },
  ];
  const admin: Row[] = [
    { icon: "stats-chart-outline", label: "Compliance dashboard", to: "/compliance", id: "compliance" },
    { icon: "create-outline", label: "Post company update", to: "/compose?type=update", id: "post-update" },
    { icon: "document-attach-outline", label: "Add policy or procedure", to: "/compose?type=policy", id: "post-policy" },
    { icon: "calendar-number-outline", label: "Create event", to: "/compose?type=event", id: "post-event" },
    { icon: "person-add-outline", label: "Assign task", to: "/compose?type=task", id: "post-task" },
    { icon: "chatbubbles-outline", label: "New chat channel", to: "/compose?type=channel", id: "post-channel" },
    { icon: "extension-puzzle-outline", label: "Integrations", to: "/integrations", id: "integrations" },
  ];

  const Group = ({ rows }: { rows: Row[] }) => (
    <View style={styles.group}>
      {rows.map((r, i) => (
        <Pressable
          key={r.id}
          testID={`library-row-${r.id}`}
          onPress={() => router.push(r.to)}
          style={({ pressed }) => [styles.row, pressed && { backgroundColor: colors.surfaceSecondary }]}
        >
          <IconBox name={r.icon} size={36} />
          <View style={[styles.rowBody, i < rows.length - 1 && styles.rowBorder]}>
            <Text style={styles.rowLabel}>{r.label}</Text>
            {!!r.count && r.count > 0 && (
              <View style={styles.count}>
                <Text style={styles.countText}>{r.count}</Text>
              </View>
            )}
            <Ionicons name="chevron-forward" size={18} color={colors.borderStrong} />
          </View>
        </Pressable>
      ))}
    </View>
  );

  return (
    <View style={styles.root} testID="library-screen">
      <TabHeader title="Library" />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: bottomChrome + 24 }}>
        <View style={styles.profile} testID="library-profile-card">
          <Avatar name={user?.name} picture={user?.picture} size={56} />
          <View style={{ flex: 1, gap: 4 }}>
            <Text style={styles.name}>{user?.name}</Text>
            <Text style={styles.email} numberOfLines={1}>{user?.email}</Text>
            <Pill label={isAdmin ? "Admin" : "Employee"} />
          </View>
        </View>
        <Text style={styles.groupTitle}>Resources</Text>
        <Group rows={resources} />
        {isAdmin && (
          <>
            <Text style={styles.groupTitle}>Admin tools</Text>
            <Group rows={admin} />
          </>
        )}
        <Button label="Sign out" variant="secondary" icon="log-out-outline" onPress={signOut} style={{ marginTop: 24 }} testID="library-sign-out-button" />
      </ScrollView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  profile: { flexDirection: "row", alignItems: "center", gap: 16, backgroundColor: c.surface, borderRadius: 16, padding: 16 },
  name: { fontSize: 18, fontWeight: "700", color: c.onSurface },
  email: { fontSize: 13, color: c.muted },
  groupTitle: { fontSize: 13, fontWeight: "600", color: c.muted, textTransform: "uppercase", marginTop: 24, marginBottom: 8, marginLeft: 4 },
  group: { backgroundColor: c.surface, borderRadius: 16, overflow: "hidden" },
  row: { flexDirection: "row", alignItems: "center", paddingLeft: 16, gap: 12, minHeight: 56 },
  rowBody: { flex: 1, flexDirection: "row", alignItems: "center", gap: 8, paddingRight: 16, minHeight: 56 },
  rowBorder: { borderBottomWidth: 0.5, borderBottomColor: c.divider },
  rowLabel: { flex: 1, fontSize: 16, color: c.onSurface },
  count: { minWidth: 22, height: 22, borderRadius: 11, backgroundColor: c.accent, alignItems: "center", justifyContent: "center", paddingHorizontal: 6 },
  countText: { color: c.onBrandPrimary, fontSize: 12, fontWeight: "700" },
}));
