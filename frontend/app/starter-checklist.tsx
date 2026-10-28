import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { ErrorState, IconName, Ionicons, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const ICON: Record<string, IconName> = { form: "clipboard-outline", policies: "shield-checkmark-outline", certificate: "ribbon-outline" };

export default function StarterChecklist() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery<any>({ queryKey: ["starter-checklist"], queryFn: () => api("/starter-checklist") });

  const toggle = async (item: any) => {
    try {
      await api(`/starter-checklist/${encodeURIComponent(item.key)}`, { method: "POST" });
      qc.invalidateQueries({ queryKey: ["starter-checklist"] });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const go = (item: any) => {
    if (item.type === "form") {
      const sep = item.url.includes("?") ? "&" : "?";
      openLink(`${item.url}${sep}name=${encodeURIComponent(user?.name ?? "")}&email=${encodeURIComponent(user?.email ?? "")}`);
    } else if (item.type === "policies") router.push("/policies");
    else router.push("/upload-certificate");
  };

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message="Couldn't load your checklist." onRetry={() => q.refetch()} />;
  const { items, done, total } = q.data;
  const pct = total ? done / total : 0;

  return (
    <View style={styles.root} testID="starter-checklist-screen">
      <FlatList
        data={items}
        keyExtractor={(i) => i.key}
        contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
        ListHeaderComponent={
          <View style={styles.hero} testID="starter-progress">
            <Text style={styles.heroTitle}>{done === total ? "You're all set! 🎉" : "Welcome to Aspire & Grow"}</Text>
            <Text style={styles.heroSub}>{done} of {total} steps complete</Text>
            <View style={styles.bar}>
              <View style={[styles.barFill, { width: `${Math.round(pct * 100)}%` }]} />
            </View>
          </View>
        }
        renderItem={({ item, index }) => (
          <View style={[styles.card, item.done && styles.cardDone]} testID={`starter-item-${item.key}`}>
            <Pressable
              onPress={() => item.type === "form" && toggle(item)}
              disabled={item.type !== "form"}
              hitSlop={6}
              style={styles.check}
              testID={`starter-toggle-${item.key}`}
              accessibilityLabel={item.type === "form" ? (item.done ? "Mark not done" : "Mark done") : undefined}
            >
              <Ionicons name={item.done ? "checkmark-circle" : "ellipse-outline"} size={28} color={item.done ? colors.success : colors.brandPrimary} />
            </Pressable>
            <Pressable onPress={() => go(item)} style={{ flex: 1, gap: 2 }} testID={`starter-open-${item.key}`}>
              <View style={styles.titleRow}>
                <Ionicons name={ICON[item.type]} size={15} color={colors.muted} />
                <Text style={styles.step}>Step {index + 1}</Text>
              </View>
              <Text style={[styles.title, item.done && styles.doneText]}>{item.title}</Text>
              {!!item.description && <Text style={styles.sub} numberOfLines={2}>{item.description}</Text>}
              <Text style={styles.hint}>
                {item.type === "form"
                  ? item.done ? "Submitted · tap the circle to undo" : "Open the form, then tap the circle when submitted"
                  : item.type === "policies"
                    ? `${item.progress[0]} of ${item.progress[1]} acknowledged · ticks itself off`
                    : item.done ? `${item.progress[0]} uploaded` : "Ticks itself off when you upload one"}
              </Text>
            </Pressable>
            <Pressable onPress={() => go(item)} hitSlop={6} style={styles.check} accessibilityLabel="Open">
              <Ionicons name="chevron-forward" size={18} color={colors.muted} />
            </Pressable>
          </View>
        )}
      />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  hero: { backgroundColor: c.brandPrimary, borderRadius: 18, padding: 20, gap: 6, marginBottom: 6 },
  heroTitle: { fontSize: 20, fontWeight: "800", color: c.onBrandPrimary },
  heroSub: { fontSize: 14, color: c.onBrandPrimary, opacity: 0.9 },
  bar: { height: 10, borderRadius: 5, backgroundColor: "rgba(255,255,255,0.3)", overflow: "hidden", marginTop: 6 },
  barFill: { height: 10, borderRadius: 5, backgroundColor: c.onBrandPrimary },
  card: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: c.surface, borderRadius: 16, padding: 12 },
  cardDone: { opacity: 0.75 },
  check: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  step: { fontSize: 12, fontWeight: "700", color: c.muted, textTransform: "uppercase" },
  title: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  doneText: { textDecorationLine: "line-through", color: c.muted },
  sub: { fontSize: 13, color: c.onSurfaceSecondary },
  hint: { fontSize: 12, color: c.brandPrimary, marginTop: 2 },
}));
