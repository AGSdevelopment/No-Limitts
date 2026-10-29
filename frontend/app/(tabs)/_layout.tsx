import { Platform } from "react-native";
import { Tabs } from "expo-router";
import { NativeTabs } from "expo-router/unstable-native-tabs";
import * as Haptics from "expo-haptics";

import { Ionicons } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { useTheme } from "@/src/theme";

export default function TabsLayout() {
  const { colors } = useTheme();

  if (usesNativeTabs) {
    return (
      <NativeTabs tintColor={colors.brandPrimary}>
        <NativeTabs.Trigger name="index">
          <NativeTabs.Trigger.Icon sf="house.fill" />
          <NativeTabs.Trigger.Label>Home</NativeTabs.Trigger.Label>
        </NativeTabs.Trigger>
        <NativeTabs.Trigger name="chat">
          <NativeTabs.Trigger.Icon sf="bubble.left.and.bubble.right.fill" />
          <NativeTabs.Trigger.Label>Chat</NativeTabs.Trigger.Label>
        </NativeTabs.Trigger>
        <NativeTabs.Trigger name="certificates">
          <NativeTabs.Trigger.Icon sf="checkmark.seal.fill" />
          <NativeTabs.Trigger.Label>Certificates</NativeTabs.Trigger.Label>
        </NativeTabs.Trigger>
        <NativeTabs.Trigger name="socials">
          <NativeTabs.Trigger.Icon sf="megaphone.fill" />
          <NativeTabs.Trigger.Label>Socials</NativeTabs.Trigger.Label>
        </NativeTabs.Trigger>
        <NativeTabs.Trigger name="library">
          <NativeTabs.Trigger.Icon sf="books.vertical.fill" />
          <NativeTabs.Trigger.Label>Library</NativeTabs.Trigger.Label>
        </NativeTabs.Trigger>
      </NativeTabs>
    );
  }

  const icon = (on: any, off: any) => {
    const TabIcon = ({ focused, color }: { focused: boolean; color: any }) => (
      <Ionicons name={focused ? on : off} size={24} color={color} />
    );
    return TabIcon;
  };

  return (
    <Tabs
      screenListeners={{ tabPress: () => Haptics.selectionAsync().catch(() => {}) }}
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.brandPrimary,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
          ...(Platform.OS === "web" ? { height: 64 } : {}),
        },
        tabBarItemStyle: { alignSelf: "center" },
        tabBarLabelStyle: { fontSize: 11, fontFamily: "Nunito-700" },
      }}
    >
      <Tabs.Screen name="index" options={{ title: "Home", tabBarIcon: icon("home", "home-outline"), tabBarButtonTestID: "tab-home" }} />
      <Tabs.Screen name="chat" options={{ title: "Chat", tabBarIcon: icon("chatbubbles", "chatbubbles-outline"), tabBarButtonTestID: "tab-chat" }} />
      <Tabs.Screen
        name="certificates"
        options={{ title: "Certificates", tabBarIcon: icon("ribbon", "ribbon-outline"), tabBarButtonTestID: "tab-certificates" }}
      />
      <Tabs.Screen name="socials" options={{ title: "Socials", tabBarIcon: icon("megaphone", "megaphone-outline"), tabBarButtonTestID: "tab-socials" }} />
      <Tabs.Screen name="library" options={{ title: "Library", tabBarIcon: icon("library", "library-outline"), tabBarButtonTestID: "tab-library" }} />
    </Tabs>
  );
}
