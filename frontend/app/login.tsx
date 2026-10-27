import { Text, View } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth";
import { Button, Ionicons } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const FEATURES: { icon: any; text: string }[] = [
  { icon: "chatbubbles-outline", text: "Team channels and direct messages" },
  { icon: "ribbon-outline", text: "Certificates with expiry reminders" },
  { icon: "document-text-outline", text: "Policies, updates, events and tasks" },
];

export default function Login() {
  const { signIn, signingIn, error } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();

  return (
    <View style={styles.root} testID="login-screen">
      <View style={styles.heroWrap}>
        <Image
          source={require("@/assets/images/welcome-team.jpg")}
          style={styles.hero}
          contentFit="cover"
          contentPosition={{ left: "50%", top: "70%" }}
          testID="login-hero-image"
        />
        <LinearGradient colors={["rgba(32,88,144,0)", "rgba(32,88,144,0.35)"]} style={styles.heroOverlay} />
      </View>
      <Animated.View entering={FadeInDown.duration(500)} style={[styles.panel, { paddingBottom: insets.bottom + 24 }]}>
        <Image source={require("@/assets/images/brand-logo.png")} style={styles.logo} contentFit="contain" testID="login-brand-logo" />
        <Text style={styles.title}>Everything your team needs, in one place.</Text>
        <View style={styles.features}>
          {FEATURES.map((f) => (
            <View key={f.text} style={styles.featureRow}>
              <Ionicons name={f.icon} size={20} color={colors.brandPrimary} />
              <Text style={styles.featureText}>{f.text}</Text>
            </View>
          ))}
        </View>
        {error && (
          <Text style={styles.error} testID="login-error">
            {error}
          </Text>
        )}
        <Button label="Continue with Google" icon="logo-google" loading={signingIn} onPress={signIn} testID="login-google-button" />
        <Text style={styles.foot}>Use your work Google account to sign in.</Text>
      </Animated.View>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  heroWrap: { flex: 1, minHeight: 260 },
  hero: { ...({ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 } as const) },
  heroOverlay: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  logo: { width: 140, height: 160, alignSelf: "center", marginTop: -96, marginBottom: 12, backgroundColor: c.surface, borderRadius: 20 },
  panel: { backgroundColor: c.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, marginTop: -24, padding: 24 },
  title: { fontSize: 28, fontWeight: "700", color: c.onSurface, letterSpacing: -0.6, lineHeight: 34 },
  features: { marginTop: 20, marginBottom: 28, gap: 14 },
  featureRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  featureText: { fontSize: 15, color: c.onSurfaceSecondary },
  error: { color: c.errorText, marginBottom: 12, fontSize: 14 },
  foot: { textAlign: "center", color: c.muted, fontSize: 13, marginTop: 12 },
}));
