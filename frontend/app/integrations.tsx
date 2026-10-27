import { useCallback, useState } from "react";
import { Pressable, RefreshControl, Switch, Text, TextInput, View } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, ConfirmSheet, EmptyState, IconBox, Ionicons, Loading, Pill } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function Integrations() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const drive = useQuery<any>({ queryKey: ["drive-status"], queryFn: () => api("/integrations/google-drive/status") });
  const gc = useQuery<any>({ queryKey: ["gchat-status"], queryFn: () => api("/integrations/google-chat/status"), enabled: user?.role === "admin" });
  const convs = useQuery<any[]>({ queryKey: ["conversations"], queryFn: () => api("/conversations") });
  const channels = (convs.data ?? []).filter((c) => c.type === "channel");
  const [editing, setEditing] = useState<string | null>(null);
  const [hook, setHook] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmDrive, setConfirmDrive] = useState(false);

  useFocusEffect(
    useCallback(() => {
      drive.refetch();
      gc.refetch();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []),
  );

  const connectDrive = async () => {
    setBusy(true);
    try {
      const r = await api("/integrations/google-drive/start", { method: "POST" });
      await openLink(r.authorization_url);
      drive.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const disconnectDrive = async () => {
    await api("/integrations/google-drive", { method: "DELETE" }).catch(() => {});
    setConfirmDrive(false);
    drive.refetch();
    toast("Google Drive disconnected", "info");
  };

  const saveHook = async (convId: string) => {
    setBusy(true);
    try {
      const r = await api(`/channels/${convId}/google-chat`, { method: "PUT", body: { webhook_url: hook } });
      setHook("");
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["conversations"] });
      toast(r.test_delivered ? "Linked — test message sent to Google Chat" : "Linked, but the test message failed", r.test_delivered ? "success" : "error");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const removeHook = async (convId: string) => {
    await api(`/channels/${convId}/google-chat`, { method: "DELETE" }).catch(() => {});
    qc.invalidateQueries({ queryKey: ["conversations"] });
    toast("Google Chat unlinked", "info");
  };
  const connectChat = async () => {
    setBusy(true);
    try {
      const r = await api("/integrations/google-chat/start", { method: "POST" });
      await openLink(r.authorization_url);
      gc.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const disconnectChat = async () => {
    await api("/integrations/google-chat", { method: "DELETE" }).catch(() => {});
    gc.refetch();
    qc.invalidateQueries({ queryKey: ["conversations"] });
  };
  const setTwoWay = async (convId: string, enabled: boolean) => {
    try {
      await api(`/channels/${convId}/google-chat/two-way`, { method: "PUT", body: { enabled } });
      qc.invalidateQueries({ queryKey: ["conversations"] });
      toast(enabled ? "Two-way sync on" : "Two-way sync off", enabled ? "success" : "info");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  if (drive.isLoading) return <Loading />;
  if (user?.role !== "admin") {
    return <EmptyState icon="lock-closed-outline" title="Admins only" subtitle="Only admins can manage integrations." testID="integrations-admin-only" />;
  }
  const d = drive.data ?? {};

  return (
    <KeyboardAwareScrollView
      style={styles.root}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 24 }}
      keyboardShouldPersistTaps="handled"
      bottomOffset={24}
      refreshControl={<RefreshControl refreshing={drive.isRefetching} onRefresh={() => { drive.refetch(); convs.refetch(); }} tintColor={colors.brandPrimary} />}
      testID="integrations-screen"
    >
      {/* Google Drive */}
      <View style={styles.card} testID="integration-google-drive">
        <View style={styles.head}>
          <IconBox name="logo-google" />
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Google Drive</Text>
            <Text style={styles.sub}>Copy certificates to Drive and attach Drive files to policies</Text>
          </View>
          {d.connected && <Pill label="Connected" />}
        </View>
        {!d.configured ? (
          <Text style={styles.note} testID="drive-not-configured">
            Waiting for Google Drive app credentials. Once they&apos;re added, you can connect your company Google account here.
          </Text>
        ) : d.connected ? (
          <>
            <Text style={styles.note} testID="drive-connected-email">
              Linked to {d.email}. New certificates are copied to the “{d.folder_name}” folder.
            </Text>
            <Button label="Disconnect" variant="secondary" onPress={() => setConfirmDrive(true)} testID="drive-disconnect-button" />
          </>
        ) : (
          <>
            <Text style={styles.note}>Sign in with the company Google account that should store the files.</Text>
            <Button label="Connect Google Drive" icon="link-outline" loading={busy} onPress={connectDrive} testID="drive-connect-button" />
          </>
        )}
      </View>

      {/* Google Chat */}
      <View style={styles.card} testID="integration-google-chat">
        <View style={styles.head}>
          <IconBox name="chatbubbles-outline" />
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Google Chat</Text>
            <Text style={styles.sub}>Copy channel messages into a Google Chat space</Text>
          </View>
        </View>
        <Text style={styles.note}>
          In Google Chat on a computer: open the space → Apps & integrations → Add webhooks → copy the link and paste it below.
        </Text>
        <View style={styles.twoWayBox} testID="gchat-reader-status">
          <Text style={styles.twoWayTitle}>Two-way sync</Text>
          {!gc.data?.configured ? (
            <Text style={styles.note}>Waiting for Google sign-in credentials before replies can sync back.</Text>
          ) : gc.data?.connected ? (
            <>
              <Text style={styles.note}>Google account connected. Turn on two-way for each channel below.</Text>
              {!!gc.data?.last_error && <Text style={styles.err}>{gc.data.last_error}</Text>}
              <Button label="Disconnect Google account" variant="ghost" onPress={disconnectChat} testID="gchat-reader-disconnect" />
            </>
          ) : (
            <>
              <Text style={styles.note}>Sign in with a Google Workspace account that is a member of the spaces.</Text>
              <Button label="Connect Google account" icon="link-outline" loading={busy} onPress={connectChat} testID="gchat-reader-connect" />
            </>
          )}
        </View>
        {channels.map((c) => (
          <View key={c.conversation_id} style={styles.channel} testID={`gchat-channel-${c.name}`}>
            <View style={styles.channelRow}>
              <Text style={styles.channelName}>#{c.name}</Text>
              {c.google_chat ? (
                <>
                  <View style={{ justifyContent: "center" }}>
                    <Pill label="Linked" />
                  </View>
                  <Pressable testID={`gchat-unlink-${c.name}`} onPress={() => removeHook(c.conversation_id)} hitSlop={8} style={styles.linkBtn}>
                    <Text style={styles.linkDanger}>Unlink</Text>
                  </Pressable>
                </>
              ) : (
                <Pressable testID={`gchat-link-${c.name}`} onPress={() => { setEditing(c.conversation_id); setHook(""); }} hitSlop={8} style={styles.linkBtn}>
                  <Text style={styles.link}>Link</Text>
                </Pressable>
              )}
            </View>
            {c.google_chat && (
              <View style={styles.channelRow}>
                <Text style={styles.twoWayLabel}>
                  {c.google_chat_two_way && !gc.data?.connected ? "Two-way on, paused until a Google account is connected" : "Two-way (Google Chat replies show here)"}
                </Text>
                <Switch
                  testID={`gchat-two-way-${c.name}`}
                  value={!!c.google_chat_two_way}
                  onValueChange={(v) => setTwoWay(c.conversation_id, v)}
                  trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }}
                />
              </View>
            )}
            {editing === c.conversation_id && (
              <View style={{ gap: 8, marginTop: 8 }}>
                <TextInput
                  testID={`gchat-webhook-input-${c.name}`}
                  value={hook}
                  onChangeText={setHook}
                  placeholder="https://chat.googleapis.com/v1/spaces/…"
                  placeholderTextColor={colors.muted}
                  autoCapitalize="none"
                  autoCorrect={false}
                  style={styles.input}
                />
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <Button label="Cancel" variant="ghost" onPress={() => setEditing(null)} style={{ flex: 1 }} testID={`gchat-cancel-${c.name}`} />
                  <Button label="Save" loading={busy} disabled={!hook.trim()} onPress={() => saveHook(c.conversation_id)} style={{ flex: 1 }} testID={`gchat-save-${c.name}`} />
                </View>
              </View>
            )}
          </View>
        ))}
      </View>

      {/* Jotform */}
      <Pressable style={styles.card} onPress={() => router.push("/forms")} testID="integration-jotform">
        <View style={styles.head}>
          <IconBox name="clipboard-outline" />
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Jotform</Text>
            <Text style={styles.sub}>Add company forms employees can fill in</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.muted} />
        </View>
      </Pressable>

      {/* Claude */}
      <Pressable style={styles.card} onPress={() => router.push("/assistant")} testID="integration-claude">
        <View style={styles.head}>
          <IconBox name="sparkles" />
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Claude AI</Text>
            <Text style={styles.sub}>Policy Q&A assistant and certificate auto-fill — active</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.muted} />
        </View>
      </Pressable>
      <ConfirmSheet visible={confirmDrive} title="Disconnect Google Drive?" message="New certificates will no longer be copied to Drive. Existing files stay in Drive." confirmLabel="Disconnect" onConfirm={disconnectDrive} onClose={() => setConfirmDrive(false)} />
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 16, marginBottom: 12, gap: 12 },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  title: { fontSize: 17, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted, marginTop: 2 },
  note: { fontSize: 14, color: c.onSurfaceSecondary, lineHeight: 20 },
  channel: { borderTopWidth: 0.5, borderTopColor: c.divider, paddingTop: 10 },
  channelRow: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 44 },
  channelName: { flex: 1, fontSize: 16, fontWeight: "600", color: c.onSurface },
  linkBtn: { minHeight: 44, justifyContent: "center", paddingHorizontal: 4 },
  link: { color: c.brandPrimary, fontWeight: "600", fontSize: 15 },
  linkDanger: { color: c.errorText, fontWeight: "600", fontSize: 15 },
  input: { minHeight: 48, borderRadius: 12, backgroundColor: c.surfaceSecondary, paddingHorizontal: 14, fontSize: 15, color: c.onSurface },
  twoWayBox: { backgroundColor: c.brandTertiary, borderRadius: 12, padding: 12, gap: 8 },
  twoWayTitle: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  twoWayLabel: { flex: 1, fontSize: 14, color: c.onSurfaceSecondary },
  err: { fontSize: 13, color: c.errorText },
}));
