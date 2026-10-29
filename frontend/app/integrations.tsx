import { useCallback, useState } from "react";
import { Pressable, RefreshControl, View } from "react-native";
import { Text, TextInput } from "@/src/components/text";
import { useFocusEffect, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, EmptyState, IconBox, Ionicons, Loading, Pill, timeAgo } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

export default function Integrations() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const drive = useQuery<any>({ queryKey: ["drive-status"], queryFn: () => api("/integrations/sharepoint/status") });
  const convs = useQuery<any[]>({ queryKey: ["conversations"], queryFn: () => api("/conversations") });
  const channels = (convs.data ?? []).filter((c) => c.type === "channel");
  const [editing, setEditing] = useState<string | null>(null);
  const [hook, setHook] = useState("");
  const [busy, setBusy] = useState(false);
  const [folderLink, setFolderLink] = useState("");
  const [editingSpace, setEditingSpace] = useState<string | null>(null);
  const [digestBusy, setDigestBusy] = useState(false);
  const ann = useQuery<any>({ queryKey: ["teams-announcements"], queryFn: () => api("/integrations/teams-announcements"), enabled: user?.role === "admin" });
  const [annHook, setAnnHook] = useState("");
  const saveAnn = async (patch: Record<string, any>) => {
    setBusy(true);
    try {
      const r = await api("/integrations/teams-announcements", { method: "PUT", body: { updates: ann.data?.updates ?? true, events: ann.data?.events ?? true, ...patch } });
      setAnnHook("");
      ann.refetch();
      if (patch.webhook_url) toast(r.test_delivered ? "Linked — test message sent to Teams" : "Linked, but the test message failed", r.test_delivered ? "success" : "error");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const removeAnn = async () => {
    await api("/integrations/teams-announcements", { method: "DELETE" }).catch(() => {});
    ann.refetch();
    toast("Announcements channel unlinked", "info");
  };
  const hasDriveFolder = Object.values(drive.data?.spaces ?? {}).some((s: any) => !!s.folder_id);
  const soc = useQuery<any>({ queryKey: ["socials"], queryFn: () => api("/socials") });
  const connectSocial = async (kind: string) => {
    setBusy(true);
    try {
      const r = await api(`/integrations/${kind}/start`, { method: "POST" });
      await openLink(r.authorization_url);
      soc.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const disconnectSocial = async (kind: string) => {
    await api(`/integrations/${kind}`, { method: "DELETE" }).catch(() => {});
    soc.refetch();
    toast("Disconnected", "info");
  };
  const syncSocial = async () => {
    try {
      const r = await api("/socials/sync", { method: "POST" });
      qc.invalidateQueries({ queryKey: ["socials"] });
      qc.invalidateQueries({ queryKey: ["updates"] });
      toast(r.imported ? `${r.imported} new post${r.imported > 1 ? "s" : ""} shared` : "No new posts", r.imported ? "success" : "info");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const idx = useQuery<any>({
    queryKey: ["drive-index"],
    queryFn: () => api("/drive/index-status"),
    enabled: user?.role === "admin" && hasDriveFolder,
    refetchInterval: (query) => (query.state.data?.running ? 4000 : false),
  });
  const reindex = async () => {
    try {
      await api("/drive/reindex", { method: "POST" });
      toast("Refreshing Drive documents", "info");
      setTimeout(() => idx.refetch(), 800);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const [resBusy, setResBusy] = useState(false);
  const testResDigest = async () => {
    setResBusy(true);
    try {
      const r = await api("/digest/resources/test", { method: "POST" });
      toast(r.sent ? `Preview sent to ${r.email}` : `Preview built but no email sent to ${r.email}`, r.sent ? "success" : "info");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setResBusy(false);
    }
  };
  const testDigest = async () => {
    setDigestBusy(true);
    try {
      const r = await api("/digest/test", { method: "POST" });
      toast(r.sent ? `Preview sent to ${r.email}` : `Preview built (${r.channels} channels) but no email sent to ${r.email}`, r.sent ? "success" : "info");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setDigestBusy(false);
    }
  };

  const saveFolder = async (space: string) => {
    setBusy(true);
    try {
      const r = await api("/integrations/sharepoint/shared-folder", { method: "PUT", body: { link: folderLink, space } });
      setFolderLink("");
      setEditingSpace(null);
      drive.refetch();
      qc.invalidateQueries({ queryKey: ["drive-shared"] });
      setTimeout(() => qc.invalidateQueries({ queryKey: ["drive-index"] }), 800);
      toast(`Folder set to “${r.folder_name}”`, "success");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  useFocusEffect(
    useCallback(() => {
      drive.refetch();
      soc.refetch();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []),
  );

  const saveHook = async (convId: string) => {
    setBusy(true);
    try {
      const r = await api(`/channels/${convId}/teams`, { method: "PUT", body: { webhook_url: hook } });
      setHook("");
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["conversations"] });
      toast(r.test_delivered ? "Linked — test message sent to Teams" : "Linked, but the test message failed", r.test_delivered ? "success" : "error");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const removeHook = async (convId: string) => {
    await api(`/channels/${convId}/teams`, { method: "DELETE" }).catch(() => {});
    qc.invalidateQueries({ queryKey: ["conversations"] });
    toast("Teams channel unlinked", "info");
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
      {/* Microsoft 365: SharePoint */}
      <View style={styles.card} testID="integration-sharepoint">
        <View style={styles.head}>
          <IconBox name="logo-microsoft" />
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>SharePoint</Text>
            <Text style={styles.sub}>Company files for staff, certificate copies and policy attachments</Text>
          </View>
          {d.configured && <Pill label="Connected" />}
        </View>
        {!d.configured ? (
          <Text style={styles.note} testID="sharepoint-not-configured">
            Waiting for the Microsoft 365 app details. Once they&apos;re added, SharePoint, Outlook invites and Microsoft sign-in all switch on.
          </Text>
        ) : (
          <>
            <Text style={styles.note}>New certificates are copied to a “{d.folder_name}” folder inside Staff Resources.</Text>
            {(["therapist", "participant"] as const).map((key) => {
              const sp = d.spaces?.[key] ?? {};
              const editing = editingSpace === key || !sp.folder_id;
              return (
                <View key={key} style={styles.twoWayBox} testID={`drive-shared-folder-${key}`}>
                  <Text style={styles.twoWayTitle}>{sp.label}</Text>
                  {!editing ? (
                    <>
                      <Text style={styles.note} testID={`drive-shared-folder-name-${key}`}>Staff browse “{sp.folder_name}” from Library → Company Drive → {sp.label}.</Text>
                      <Button label="Change folder" variant="ghost" onPress={() => { setEditingSpace(key); setFolderLink(""); }} testID={`drive-shared-folder-change-${key}`} />
                    </>
                  ) : (
                    <>
                      <Text style={styles.note}>In SharePoint, open the folder for {sp.label} → Copy link, then paste it here.</Text>
                      <TextInput
                        testID={`drive-shared-folder-input-${key}`}
                        value={editingSpace === key ? folderLink : ""}
                        onFocus={() => setEditingSpace(key)}
                        onChangeText={(t) => { setEditingSpace(key); setFolderLink(t); }}
                        placeholder="https://nolimitts.sharepoint.com/…"
                        placeholderTextColor={colors.muted}
                        autoCapitalize="none"
                        autoCorrect={false}
                        style={[styles.input, { backgroundColor: colors.surface }]}
                      />
                      <Button label="Save folder" loading={busy && editingSpace === key} disabled={editingSpace !== key || !folderLink.trim()} onPress={() => saveFolder(key)} testID={`drive-shared-folder-save-${key}`} />
                      {!!sp.folder_id && (
                        <Button label="Cancel" variant="ghost" onPress={() => { setEditingSpace(null); setFolderLink(""); }} testID={`drive-shared-folder-cancel-${key}`} />
                      )}
                    </>
                  )}
                </View>
              );
            })}
          </>
        )}
      </View>

      {/* Outlook calendar */}
      <View style={styles.card} testID="integration-outlook">
        <View style={styles.head}>
          <IconBox name="calendar-outline" />
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Outlook calendar</Text>
            <Text style={styles.sub}>Check-in invites are sent from the booking admin&apos;s Outlook calendar</Text>
          </View>
          {d.configured && <Pill label="On" />}
        </View>
        {!d.configured && <Text style={styles.note} testID="outlook-not-configured">Switches on with the Microsoft 365 app details.</Text>}
      </View>

      {/* Microsoft Teams */}
      <View style={styles.card} testID="integration-teams">
        <View style={styles.head}>
          <IconBox name="chatbubbles-outline" />
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Microsoft Teams</Text>
            <Text style={styles.sub}>Copy channel messages into a Teams channel</Text>
          </View>
        </View>
        <Text style={styles.note}>
          In Teams: open the channel → ••• → Workflows → “Post to a channel when a webhook request is received” → copy the link and paste it below.
        </Text>
        <View style={styles.twoWayBox} testID="teams-announcements">
          <Text style={styles.twoWayTitle}>Announcements channel {ann.data?.linked ? "· Linked" : ""}</Text>
          <Text style={styles.note}>New company updates and events are posted here automatically.</Text>
          <TextInput
            testID="teams-announcements-input"
            value={annHook}
            onChangeText={setAnnHook}
            placeholder={ann.data?.linked ? "Paste a new link to change channel" : "https://….logic.azure.com/…"}
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
            autoCorrect={false}
            style={[styles.input, { backgroundColor: colors.surface }]}
          />
          {ann.data?.linked && (
            <View style={{ gap: 8 }}>
              {(["updates", "events"] as const).map((k) => (
                <Pressable key={k} onPress={() => saveAnn({ [k]: !ann.data[k] })} style={styles.channelRow} testID={`teams-announcements-toggle-${k}`}>
                  <Ionicons name={ann.data[k] ? "checkbox" : "square-outline"} size={22} color={colors.brandPrimary} />
                  <Text style={styles.channelName}>{k === "updates" ? "Company updates" : "New events"}</Text>
                </Pressable>
              ))}
            </View>
          )}
          <View style={{ flexDirection: "row", gap: 8 }}>
            {ann.data?.linked && <Button label="Unlink" variant="ghost" onPress={removeAnn} style={{ flex: 1 }} testID="teams-announcements-unlink" />}
            <Button label="Save" loading={busy} disabled={!annHook.trim()} onPress={() => saveAnn({ webhook_url: annHook })} style={{ flex: 1 }} testID="teams-announcements-save" />
          </View>
        </View>
        <Text style={styles.twoWayTitle}>Copy chat channels to Teams</Text>
        {channels.map((c) => (
          <View key={c.conversation_id} style={styles.channel} testID={`teams-channel-${c.name}`}>
            <View style={styles.channelRow}>
              <Text style={styles.channelName}>#{c.name}</Text>
              {c.teams ? (
                <>
                  <View style={{ justifyContent: "center" }}>
                    <Pill label="Linked" />
                  </View>
                  <Pressable testID={`teams-unlink-${c.name}`} onPress={() => removeHook(c.conversation_id)} hitSlop={8} style={styles.linkBtn}>
                    <Text style={styles.linkDanger}>Unlink</Text>
                  </Pressable>
                </>
              ) : (
                <Pressable testID={`teams-link-${c.name}`} onPress={() => { setEditing(c.conversation_id); setHook(""); }} hitSlop={8} style={styles.linkBtn}>
                  <Text style={styles.link}>Link</Text>
                </Pressable>
              )}
            </View>
            {editing === c.conversation_id && (
              <View style={{ gap: 8, marginTop: 8 }}>
                <TextInput
                  testID={`teams-webhook-input-${c.name}`}
                  value={hook}
                  onChangeText={setHook}
                  placeholder="https://….logic.azure.com/…"
                  placeholderTextColor={colors.muted}
                  autoCapitalize="none"
                  autoCorrect={false}
                  style={styles.input}
                />
                <View style={{ flexDirection: "row", gap: 8 }}>
                  <Button label="Cancel" variant="ghost" onPress={() => setEditing(null)} style={{ flex: 1 }} testID={`teams-cancel-${c.name}`} />
                  <Button label="Save" loading={busy} disabled={!hook.trim()} onPress={() => saveHook(c.conversation_id)} style={{ flex: 1 }} testID={`teams-save-${c.name}`} />
                </View>
              </View>
            )}
          </View>
        ))}
      </View>

      {/* Social media */}
      <View style={styles.card} testID="integration-socials">
        <View style={styles.head}>
          <IconBox name="share-social-outline" />
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Social media</Text>
            <Text style={styles.sub}>New posts are shared to Socials and Company updates automatically</Text>
          </View>
        </View>
        {([
          { key: "meta", label: "Facebook + Instagram", s: soc.data?.status?.meta, hint: "Sign in with a Facebook account that manages the No Limitts Page (its linked Instagram comes too)." },
        ] as const).map((o) => (
          <View key={o.key} style={styles.twoWayBox} testID={`social-${o.key}`}>
            <View style={styles.channelRow}>
              <Text style={[styles.twoWayTitle, { flex: 1 }]}>{o.label}</Text>
              {o.s?.connected && <Pill label="Connected" />}
            </View>
            {!o.s?.configured ? (
              <Text style={styles.note} testID={`social-${o.key}-not-configured`}>Waiting for app credentials before this can be connected.</Text>
            ) : o.s?.connected ? (
              <>
                <Text style={styles.note}>
                  {o.key === "meta" ? `Page: ${o.s.name}${o.s.instagram ? ` · Instagram @${o.s.instagram}` : ""}` : `Company page: ${o.s.name || "connected"}`}
                </Text>
                {!!o.s.last_error && <Text style={styles.err}>{o.s.last_error}</Text>}
                <Button label="Disconnect" variant="ghost" onPress={() => disconnectSocial(o.key)} testID={`social-${o.key}-disconnect`} />
              </>
            ) : (
              <>
                <Text style={styles.note}>{o.hint}</Text>
                <Button label={`Connect ${o.label}`} icon="link-outline" loading={busy} onPress={() => connectSocial(o.key)} testID={`social-${o.key}-connect`} />
              </>
            )}
          </View>
        ))}
        {soc.data?.status?.meta?.connected && (
          <Button label="Check for new posts now" variant="secondary" icon="refresh" onPress={syncSocial} testID="social-sync-now" />
        )}
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
      <View style={styles.card} testID="integration-claude">
        <Pressable style={styles.head} onPress={() => router.push("/assistant")} testID="integration-claude-open">
          <IconBox name="sparkles" />
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Claude AI</Text>
            <Text style={styles.sub}>Policy & Drive Q&A, chat summaries and certificate auto-fill — active</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={colors.muted} />
        </Pressable>
        {hasDriveFolder && (
          <View style={styles.twoWayBox} testID="ai-drive-index">
            <Text style={styles.twoWayTitle}>Reads the Company Drive folder</Text>
            <Text style={styles.note} testID="ai-drive-index-status">
              {idx.data?.running
                ? "Reading documents now…"
                : `${idx.data?.count ?? 0} documents readable${idx.data?.last_run ? ` · checked ${timeAgo(idx.data.last_run)}` : ""}. Refreshes every 4 hours.`}
            </Text>
            <Button label="Refresh now" variant="ghost" icon="refresh" onPress={reindex} testID="ai-drive-reindex" />
          </View>
        )}
        <View style={styles.twoWayBox} testID="digest-box">
          <Text style={styles.twoWayTitle}>Weekly chat digest</Text>
          <Text style={styles.note}>Every Monday at 8am Perth time, everyone gets an email recap of last week&apos;s team channels.</Text>
          <Button label="Email me a preview" variant="ghost" icon="mail-outline" loading={digestBusy} onPress={testDigest} testID="digest-test-button" />
        </View>
        <View style={styles.twoWayBox} testID="resource-digest-box">
          <Text style={styles.twoWayTitle}>Weekly Company Drive digest</Text>
          <Text style={styles.note}>Every Monday at 8am Perth time, everyone gets an email of new templates, resources and the top-rated suppliers.</Text>
          <Button label="Email me a preview" variant="ghost" icon="mail-outline" loading={resBusy} onPress={testResDigest} testID="resource-digest-test-button" />
        </View>
      </View>
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
