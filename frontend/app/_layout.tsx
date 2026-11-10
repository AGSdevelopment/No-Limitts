import { QueryClientProvider } from "@tanstack/react-query";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { Image, LogBox, Platform, StyleSheet, View, ActivityIndicator } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";

import { ErrorBoundary } from "@/src/components/error-boundary";
import { fonts } from "@/src/components/text";
import { ToastProvider } from "@/src/components/toast";
import { AuthProvider, useAuth } from "@/src/auth";
import { queryClient } from "@/src/query-client";
import { useTheme } from "@/src/theme";

// Disable logbox errors etc so that users can see the app
// and agent works as expected.
LogBox.ignoreAllLogs(true);

// Web (desktop, Chromebook, phone browsers): no sideways page scroll; on wide screens centre the app and its dialogs in a readable column.
if (Platform.OS === "web" && typeof document !== "undefined" && !document.getElementById("nl-web-layout")) {
  const css = document.createElement("style");
  css.id = "nl-web-layout";
  css.textContent = `
    html, body { overflow-x: hidden; background: #F3EEE6; }
    @media (min-width: 900px) {
      #root { max-width: 1040px; margin: 0 auto; box-shadow: 0 0 40px rgba(0,0,0,0.08); }
      [aria-modal="true"] { max-width: 720px; margin: 0 auto !important; box-shadow: 0 0 0 100vmax rgba(0,0,0,0.3); }
    }`;
  document.head.appendChild(css);
  document.title = "No Limitts";
}

function RootStack() {
  const { user, loading } = useAuth();
  const { colors } = useTheme();
  if (loading) {
    return (
      <View style={[styles.root, styles.center, { backgroundColor: colors.background, gap: 24 }]} testID="auth-loading">
        <Image source={require("../assets/images/splash-image.png")} style={styles.splashLogo} resizeMode="contain" />
        <ActivityIndicator size="large" color={colors.brandPrimary} />
      </View>
    );
  }
  const header = {
    headerShown: true,
    headerTintColor: colors.brandPrimary,
    headerTitleStyle: { color: colors.onSurface, fontFamily: "Nunito-700" },
    headerStyle: { backgroundColor: colors.background },
    headerShadowVisible: false,
    headerBackButtonDisplayMode: "minimal" as const,
  };
  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.background } }}>
      <Stack.Protected guard={!!user && !user.must_change_password}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="chat/[id]" options={{ ...header, title: "Chat" }} />
        <Stack.Screen name="new-chat" options={{ ...header, title: "New message", presentation: "modal" }} />
        <Stack.Screen name="upload-certificate" options={{ ...header, title: "Upload certificate", presentation: "modal" }} />
        <Stack.Screen name="compose" options={{ ...header, title: "New post", presentation: "modal" }} />
        <Stack.Screen name="updates" options={{ ...header, title: "Company updates" }} />
        <Stack.Screen name="policies" options={{ ...header, title: "Policies & procedures" }} />
        <Stack.Screen name="policy/[id]" options={{ ...header, title: "Policy" }} />
        <Stack.Screen name="events" options={{ ...header, title: "Events" }} />
        <Stack.Screen name="event-new" options={{ ...header, title: "New event" }} />
        <Stack.Screen name="event/[id]" options={{ ...header, title: "Event" }} />
        <Stack.Screen name="places" options={{ ...header, title: "No Limitts favourites" }} />
        <Stack.Screen name="directory" options={{ ...header, title: "Company Drive" }} />
        <Stack.Screen name="directory-new" options={{ ...header, title: "Add to Company Drive", presentation: "modal" }} />
        <Stack.Screen name="leaderboard" options={{ ...header, title: "Leaderboard" }} />
        <Stack.Screen name="cert-calendar" options={{ ...header, title: "Expiry calendar" }} />
        <Stack.Screen name="pm/index" options={{ ...header, title: "Participant Management" }} />
        <Stack.Screen name="pm/funding" options={{ ...header, title: "Funding" }} />
        <Stack.Screen name="pm/rostering" options={{ ...header, title: "Rostering" }} />
        <Stack.Screen name="pm/timesheets" options={{ ...header, title: "Timesheets" }} />
        <Stack.Screen name="pm/invoices" options={{ ...header, title: "Invoices" }} />
        <Stack.Screen name="pm/addresses" options={{ ...header, title: "Participant addresses" }} />
        <Stack.Screen name="pathway" options={{ ...header, title: "My therapist pathway" }} />
        <Stack.Screen name="tasks" options={{ ...header, title: "Tasks" }} />
        <Stack.Screen name="participant-groups/index" options={{ ...header, title: "Participant Groups" }} />
        <Stack.Screen name="participant-groups/[id]" options={{ ...header, title: "Group" }} />
        <Stack.Screen name="participant-groups/compliance" options={{ ...header, title: "Group task tracker" }} />
        <Stack.Screen name="reports" options={{ ...header, title: "Reports" }} />
        <Stack.Screen name="notifications" options={{ ...header, title: "Notifications" }} />
        <Stack.Screen name="team" options={{ ...header, title: "Team directory" }} />
        <Stack.Screen name="assistant" options={{ ...header, title: "Ask AI" }} />
        <Stack.Screen name="forms" options={{ ...header, title: "Forms" }} />
        <Stack.Screen name="drive" options={{ ...header, title: "Company Drive" }} />
        <Stack.Screen name="cpd" options={{ ...header, title: "CPD" }} />
        <Stack.Screen name="compliance" options={{ ...header, title: "Compliance" }} />
        <Stack.Screen name="starter-checklist" options={{ ...header, title: "First-week checklist" }} />
        <Stack.Screen name="starter/[id]" options={{ ...header, title: "Starter progress" }} />
        <Stack.Screen name="cert-requirements" options={{ ...header, title: "Required certificates" }} />
        <Stack.Screen name="staff/[id]" options={{ ...header, title: "Staff profile" }} />
        <Stack.Screen name="celebration/[key]" options={{ ...header, title: "Celebration" }} />
        <Stack.Screen name="reminder-history" options={{ ...header, title: "Reminder history" }} />
        <Stack.Screen name="integrations" options={{ ...header, title: "Integrations" }} />
        <Stack.Screen name="caseload" options={{ ...header, title: user?.user_type === "support_worker" && user?.role !== "admin" ? "My participants" : "My caseload" }} />
        <Stack.Screen name="participant/[id]" options={{ ...header, title: "Participant profile" }} />
        <Stack.Screen name="handover-photos/[id]" options={{ ...header, title: "Handover photos" }} />
        <Stack.Screen name="missed-notes" options={{ ...header, title: "Missed case notes" }} />
      </Stack.Protected>
      {/* Single change-password route: forced (no header) for temp passwords, normal from Library. */}
      <Stack.Protected guard={!!user}>
        <Stack.Screen name="change-password" options={user?.must_change_password ? { headerShown: false } : { ...header, title: "Change password" }} />
      </Stack.Protected>
      <Stack.Protected guard={!user}>
        <Stack.Screen name="login" />
      </Stack.Protected>
      <Stack.Screen name="privacy" options={{ ...header, title: "Privacy policy" }} />
      <Stack.Screen name="team-certificates" options={{ ...header, title: "Team certificates" }} />
    </Stack>
  );
}

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts(fonts);
  if (!fontsLoaded && !fontError) return null;
  return (
    <GestureHandlerRootView style={styles.root}>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <KeyboardProvider>
            <AuthProvider>
              <ToastProvider>
                <StatusBar style="dark" />
                <RootStack />
              </ToastProvider>
            </AuthProvider>
          </KeyboardProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  center: { alignItems: "center", justifyContent: "center" },
  splashLogo: { width: 260, height: 260 },
});
