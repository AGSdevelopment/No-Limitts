import { useState } from "react";
import { router } from "expo-router";
import { View } from "react-native";
import { Text } from "@/src/components/text";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { useAuth, User } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, Field, Ionicons } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

// Shown instead of the app until a Support Worker replaces their temporary password (also reachable from Library).
export default function ChangePassword() {
  const { user, setSignedInUser, signOut } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const forced = !!user?.must_change_password;
  const [current, setCurrent] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [saving, setSaving] = useState(false);
  const mismatch = !!pw2 && pw !== pw2;

  const save = async () => {
    setSaving(true);
    try {
      const u = await api<User>("/auth/change-password", { method: "POST", body: { current_password: forced ? null : current, new_password: pw } });
      toast("Password updated", "success");
      setCurrent(""); setPw(""); setPw2("");
      setSignedInUser(u);
      if (forced) router.replace("/");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <KeyboardAwareScrollView style={styles.root} bottomOffset={24} keyboardShouldPersistTaps="handled"
      contentContainerStyle={{ padding: 24, paddingTop: forced ? insets.top + 32 : 24, paddingBottom: insets.bottom + 24, gap: 14 }} testID="change-password-screen">
      <View style={styles.icon}><Ionicons name="key-outline" size={28} color={colors.brandPrimary} /></View>
      <Text style={styles.title}>{forced ? `Welcome${user?.name ? `, ${user.name.split(" ")[0]}` : ""}! Set your password` : "Change password"}</Text>
      <Text style={styles.sub}>{forced ? "Your admin gave you a temporary password. Choose your own to continue." : "Use at least 8 characters, mixing letters with numbers or symbols."}</Text>
      {!forced && <Field label="Current password" value={current} onChangeText={setCurrent} secureTextEntry autoCapitalize="none" testID="cp-current" />}
      <Field label="New password" value={pw} onChangeText={setPw} secureTextEntry autoCapitalize="none" textContentType="newPassword" placeholder="At least 8 characters" testID="cp-new" />
      <Field label="Confirm new password" value={pw2} onChangeText={setPw2} secureTextEntry autoCapitalize="none" textContentType="newPassword" testID="cp-confirm" />
      {mismatch && <Text style={styles.err} testID="cp-mismatch">Passwords don&apos;t match</Text>}
      <Button label="Save password" loading={saving} disabled={pw.length < 8 || pw !== pw2 || (!forced && !current)} onPress={save} testID="cp-save" />
      {forced && <Button label="Sign out" variant="ghost" onPress={signOut} testID="cp-sign-out" />}
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  icon: { width: 56, height: 56, borderRadius: 28, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 24, fontWeight: "800", color: c.onSurface },
  sub: { fontSize: 15, color: c.onSurfaceSecondary, lineHeight: 21 },
  err: { color: c.errorText, fontSize: 13 },
}));
