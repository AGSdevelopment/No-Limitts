import { FlatList, Pressable, RefreshControl, View } from "react-native";
import { Text } from "@/src/components/text";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { TabHeader } from "@/src/components/header";
import { SOCIAL_BRAND, SocialPost } from "@/src/components/social-post";
import { EmptyState, ErrorState, Ionicons, Loading } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { makeStyles, useTheme } from "@/src/theme";

export default function Socials() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const q = useQuery<any>({ queryKey: ["socials"], queryFn: () => api("/socials") });
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;
  const isAdmin = user?.role === "admin";

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load socials." onRetry={() => q.refetch()} />;
  const { links, websites, posts, status } = q.data;
  const anyConnected = status.meta.connected;

  const header = (
    <View style={{ gap: 12, marginBottom: 8 }}>
      <Text style={[styles.section, { marginTop: 0 }]}>Our websites</Text>
      {(websites ?? []).map((w: any) => (
        <Pressable key={w.url} testID={`socials-website-${w.label}`} onPress={() => openLink(w.url)} style={({ pressed }) => [styles.account, pressed && { opacity: 0.85 }]}>
          <View style={[styles.brandIcon, { backgroundColor: colors.brandPrimary }]}>
            <Ionicons name="globe-outline" size={24} color="#FFFFFF" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.accountName}>{w.label}</Text>
            <Text style={styles.accountHandle} numberOfLines={1}>{w.url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}</Text>
          </View>
          <Text style={styles.follow}>Visit</Text>
          <Ionicons name="open-outline" size={18} color={colors.brandPrimary} />
        </Pressable>
      ))}
      <Text style={styles.section}>Follow us</Text>
      {(["instagram", "facebook"] as const).map((k) => (
        <Pressable
          key={k}
          testID={`socials-open-${k}`}
          onPress={() => openLink(links[k].url)}
          style={({ pressed }) => [styles.account, pressed && { opacity: 0.85 }]}
        >
          <View style={[styles.brandIcon, { backgroundColor: SOCIAL_BRAND[k].color }]}>
            <Ionicons name={SOCIAL_BRAND[k].icon} size={24} color="#FFFFFF" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.accountName}>{links[k].label}</Text>
            <Text style={styles.accountHandle} numberOfLines={1}>{links[k].handle}</Text>
          </View>
          <Text style={styles.follow}>Open</Text>
          <Ionicons name="open-outline" size={18} color={colors.brandPrimary} />
        </Pressable>
      ))}
      {isAdmin && !anyConnected && (
        <Pressable testID="socials-admin-connect" onPress={() => router.push("/integrations")} style={styles.note}>
          <Ionicons name="link-outline" size={18} color={colors.brandPrimary} />
          <Text style={styles.noteText}>Connect the accounts in Integrations so new posts appear here and in Company updates automatically.</Text>
        </Pressable>
      )}
      <Text style={styles.section}>Latest posts</Text>
    </View>
  );

  return (
    <View style={styles.root} testID="socials-screen">
      <TabHeader title="Socials" />
      <FlatList
        data={posts}
        keyExtractor={(p) => p.update_id}
        ListHeaderComponent={header}
        contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: bottomChrome + 24, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
        ListEmptyComponent={
          <EmptyState icon="images-outline" title="No posts yet" subtitle="New Instagram and Facebook posts will show up here." testID="socials-empty" />
        }
        renderItem={({ item }) => <SocialPost item={item} />}
      />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  account: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: c.surface, borderRadius: 16, padding: 14, minHeight: 72 },
  brandIcon: { width: 44, height: 44, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  accountName: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  accountHandle: { fontSize: 13, color: c.muted, marginTop: 2 },
  follow: { fontSize: 14, fontWeight: "600", color: c.brandPrimary },
  note: { flexDirection: "row", gap: 10, alignItems: "center", backgroundColor: c.brandTertiary, borderRadius: 12, padding: 12, minHeight: 48 },
  noteText: { flex: 1, fontSize: 14, color: c.onSurface, lineHeight: 20 },
  section: { fontSize: 13, fontWeight: "600", color: c.muted, textTransform: "uppercase", marginTop: 12, marginLeft: 4 },
}));
