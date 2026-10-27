import { QueryClientProvider } from "@tanstack/react-query";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { LogBox, StyleSheet, View, ActivityIndicator } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";

import { ErrorBoundary } from "@/src/components/error-boundary";
import { ToastProvider } from "@/src/components/toast";
import { AuthProvider, useAuth } from "@/src/auth";
import { queryClient } from "@/src/query-client";
import { useTheme } from "@/src/theme";

// Disable logbox errors etc so that users can see the app
// and agent works as expected.
LogBox.ignoreAllLogs(true);

function RootStack() {
  const { user, loading } = useAuth();
  const { colors } = useTheme();
  if (loading) {
    return (
      <View style={[styles.root, styles.center, { backgroundColor: colors.surface }]} testID="auth-loading">
        <ActivityIndicator size="large" color={colors.brandPrimary} />
      </View>
    );
  }
  const header = {
    headerShown: true,
    headerTintColor: colors.brandPrimary,
    headerTitleStyle: { color: colors.onSurface, fontWeight: "600" as const },
    headerStyle: { backgroundColor: colors.surface },
    headerShadowVisible: false,
    headerBackButtonDisplayMode: "minimal" as const,
  };
  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.surface } }}>
      <Stack.Protected guard={!!user}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="chat/[id]" options={{ ...header, title: "Chat" }} />
        <Stack.Screen name="new-chat" options={{ ...header, title: "New message", presentation: "modal" }} />
        <Stack.Screen name="upload-certificate" options={{ ...header, title: "Upload certificate", presentation: "modal" }} />
        <Stack.Screen name="compose" options={{ ...header, title: "New post", presentation: "modal" }} />
        <Stack.Screen name="updates" options={{ ...header, title: "Company updates" }} />
        <Stack.Screen name="policies" options={{ ...header, title: "Policies & procedures" }} />
        <Stack.Screen name="policy/[id]" options={{ ...header, title: "Policy" }} />
        <Stack.Screen name="events" options={{ ...header, title: "Events" }} />
        <Stack.Screen name="tasks" options={{ ...header, title: "Tasks" }} />
        <Stack.Screen name="notifications" options={{ ...header, title: "Notifications" }} />
        <Stack.Screen name="team" options={{ ...header, title: "Team directory" }} />
        <Stack.Screen name="assistant" options={{ ...header, title: "Ask AI" }} />
        <Stack.Screen name="forms" options={{ ...header, title: "Forms" }} />
        <Stack.Screen name="drive" options={{ ...header, title: "Company Drive" }} />
        <Stack.Screen name="cpd" options={{ ...header, title: "CPD" }} />
        <Stack.Screen name="integrations" options={{ ...header, title: "Integrations" }} />
      </Stack.Protected>
      <Stack.Protected guard={!user}>
        <Stack.Screen name="login" />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
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
});
