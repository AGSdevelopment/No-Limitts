import { createElement, useState } from "react";
import { ActivityIndicator, Linking, Platform, Pressable, Text, View } from "react-native";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { WebView } from "react-native-webview";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken, openLink } from "@/src/api";
import { EmptyState, ErrorState, Ionicons, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

// Shows an external dashboard inside the app. The server only returns the address to allowed roles.
export default function Dashboard() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const [loading, setLoading] = useState(true);
  const q = useQuery<any>({ queryKey: ["dashboard", id], queryFn: () => api(`/dashboards/${id}`), retry: false });

  if (q.isLoading) return <Loading />;
  if (q.isError) {
    return (q.error as any)?.message === "Dashboard not found"
      ? <EmptyState icon="lock-closed-outline" title="No access" subtitle="This dashboard isn't available for your role." actionLabel="Back to Library" onAction={() => router.replace("/library")} testID="dashboard-no-access" />
      : <ErrorState message="Couldn't load the dashboard." onRetry={() => q.refetch()} />;
  }
  const d = q.data;
  const src = d.embed?.startsWith("agts") ? `${API_URL}/agts-dashboard/app?token=${encodeURIComponent(getApiToken() ?? "")}${d.embed === "agts-nk" ? `&view=nk&page=${encodeURIComponent(d.dashboard_id)}` : ""}` : d.url;
  const host = new URL(src).host;

  return (
    <View style={[styles.root, { paddingBottom: insets.bottom }]} testID="dashboard-screen">
      <Stack.Screen
        options={{
          title: d.name,
          headerRight: () => (
            <Pressable onPress={() => openLink(d.url)} style={styles.headerBtn} accessibilityLabel="Open in browser" testID="dashboard-open-browser">
              <Ionicons name="open-outline" size={22} color={colors.brandPrimary} />
            </Pressable>
          ),
        }}
      />
      {Platform.OS === "web" ? (
        createElement("iframe", { src, style: { width: "100%", height: "100%", border: 0 }, title: d.name, "data-testid": "dashboard-frame" })
      ) : (
        <View style={{ flex: 1 }}>
          <WebView
            source={{ uri: src }}
            style={{ flex: 1 }}
            onLoadEnd={() => setLoading(false)}
            setSupportMultipleWindows={false}
            sharedCookiesEnabled
            thirdPartyCookiesEnabled
            onShouldStartLoadWithRequest={(req) => {
              // Pages on the dashboard's own site stay in the app; anything else opens outside
              let reqHost = "";
              try {
                reqHost = new URL(req.url).host;
              } catch {}
              if (req.url.startsWith("http") && req.isTopFrame && reqHost !== host && !reqHost.endsWith(".wix.com") && !reqHost.endsWith(".wixsite.com")) {
                Linking.openURL(req.url).catch(() => {});
                return false;
              }
              return true;
            }}
            testID="dashboard-webview"
          />
          {loading && (
            <View style={styles.overlay}>
              <ActivityIndicator color={colors.brandPrimary} />
              <Text style={styles.sub}>Loading dashboard…</Text>
            </View>
          )}
        </View>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  headerBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  overlay: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: c.surface },
  sub: { fontSize: 14, color: c.muted },
}));
