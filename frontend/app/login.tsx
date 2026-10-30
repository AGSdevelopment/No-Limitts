import { useState } from "react";
import { Pressable, View } from "react-native";
import { useRouter } from "expo-router";
import { Text } from "@/src/components/text";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import Animated, { FadeInDown } from "react-native-reanimated";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth";
import { Button, Field } from "@/src/components/ui";
import { makeStyles } from "@/src/theme";

export default function Login() {
  const { signIn, signInWithPassword, signingIn, error } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  return (
    <KeyboardAwareScrollView style={styles.root} contentContainerStyle={{ flexGrow: 1 }} bottomOffset={24} keyboardShouldPersistTaps="handled" testID="login-screen">
      <View style={styles.heroWrap}>
        <Image source={require("@/assets/images/welcome-team.jpg")} style={styles.hero} contentFit="cover"
          contentPosition={{ left: "50%", top: "60%" }} testID="login-hero-image" />
        <LinearGradient colors={["rgba(103,62,141,0)", "rgba(103,62,141,0.35)"]} style={styles.heroOverlay} />
      </View>
      <Animated.View entering={FadeInDown.duration(500)} style={[styles.panel, { paddingBottom: insets.bottom + 24 }]}>
        <Image source={require("@/assets/images/brand-logo.png")} style={styles.logo} contentFit="contain" testID="login-brand-logo" />
        <Text style={styles.title}>Everything your team needs, in one place.</Text>
        {error && <Text style={styles.error} testID="login-error">{error}</Text>}

        <Text style={styles.group}>Executives, Admins, HR, Support Office & Coordinators</Text>
        <Button label="Sign in with Microsoft" icon="logo-microsoft" loading={signingIn && !password} onPress={signIn} testID="login-microsoft-button" />

        <View style={styles.divider}>
          <View style={styles.line} />
          <Text style={styles.or}>Support Workers</Text>
          <View style={styles.line} />
        </View>
        <View style={{ gap: 12 }}>
          <Field label="Email" value={email} onChangeText={setEmail} autoCapitalize="none" autoCorrect={false} keyboardType="email-address"
            autoComplete="email" textContentType="username" placeholder="you@example.com" testID="login-email" />
          <Field label="Password" value={password} onChangeText={setPassword} secureTextEntry autoCapitalize="none" autoComplete="password"
            textContentType="password" placeholder="From your admin" testID="login-password" onSubmitEditing={() => signInWithPassword(email, password)} />
          <Button label="Sign in" variant="secondary" icon="log-in-outline" loading={signingIn && !!password} disabled={!email.trim() || !password}
            onPress={() => signInWithPassword(email, password)} testID="login-password-button" />
        </View>
        <Text style={styles.foot}>No login yet? Ask your admin to set you up.</Text>
        <Pressable onPress={() => router.push("/privacy")} style={styles.privacy} hitSlop={8} testID="login-privacy-link" accessibilityRole="link">
          <Text style={styles.privacyText}>Privacy policy</Text>
        </Pressable>
      </Animated.View>
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  heroWrap: { height: 280 },
  hero: { ...({ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 } as const) },
  heroOverlay: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  logo: { width: 200, height: 150, alignSelf: "center", marginTop: -96, marginBottom: 12, padding: 8, backgroundColor: c.surface, borderRadius: 20 },
  panel: { flex: 1, backgroundColor: c.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, marginTop: -24, padding: 24 },
  title: { fontSize: 26, fontWeight: "700", color: c.onSurface, letterSpacing: -0.6, lineHeight: 32, marginBottom: 20 },
  group: { fontSize: 13, fontWeight: "700", color: c.muted, marginBottom: 8 },
  divider: { flexDirection: "row", alignItems: "center", gap: 10, marginVertical: 20 },
  line: { flex: 1, height: 1, backgroundColor: c.border },
  or: { fontSize: 13, fontWeight: "700", color: c.muted },
  error: { color: c.errorText, marginBottom: 12, fontSize: 14 },
  foot: { textAlign: "center", color: c.muted, fontSize: 13, marginTop: 16 },
  privacy: { alignSelf: "center", minHeight: 44, justifyContent: "center", paddingHorizontal: 12 },
  privacyText: { color: c.brandPrimary, fontSize: 13, fontWeight: "600", textDecorationLine: "underline" },
}));
