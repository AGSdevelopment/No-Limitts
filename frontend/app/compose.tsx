import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Switch, View } from "react-native";
import { Text, TextInput } from "@/src/components/text";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders } from "@/src/api";
import { uploadForm } from "@/src/utils/upload";
import * as DocumentPicker from "expo-document-picker";
import { useToast } from "@/src/components/toast";
import { useAuth } from "@/src/auth";
import { Avatar, Button, Chip, EmptyState, Field, Ionicons, dmyDate, dmyToIso } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

type Kind = "update" | "policy" | "event" | "task" | "channel";
const TITLES: Record<Kind, string> = {
  update: "Post update",
  policy: "Add policy",
  event: "Create event",
  task: "Assign task",
  channel: "New channel",
};
function inDays(n: number) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return dmyDate(d);
}

export default function Compose() {
  const { type } = useLocalSearchParams<{ type: Kind }>();
  const kind: Kind = (type && TITLES[type] ? type : "update") as Kind;
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [pinned, setPinned] = useState(false);
  const [category, setCategory] = useState<"Policy" | "Procedure">("Policy");
  const [date, setDate] = useState(inDays(7));
  const [time, setTime] = useState("");
  const [location, setLocation] = useState("");
  const [assignee, setAssignee] = useState<string | null>(null);
  const [people, setPeople] = useState<string[]>([]);
  const togglePerson = (id: string) => {
    setAssignee(null);
    setPeople((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  };
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = user?.role === "admin";
  const titleFor = kind === "task" && !isAdmin ? "New private task" : TITLES[kind];
  const users = useQuery<any[]>({ queryKey: ["users"], queryFn: () => api("/users"), enabled: kind === "task" && isAdmin });
  const driveStatus = useQuery<any>({ queryKey: ["drive-status"], queryFn: () => api("/integrations/sharepoint/status"), enabled: kind === "policy" });
  const [driveSearch, setDriveSearch] = useState("");
  const [driveFile, setDriveFile] = useState<any>(null);
  const [taskFile, setTaskFile] = useState<{ uri: string; name: string; mimeType?: string } | null>(null);
  const pickTaskFile = async () => {
    const r = await DocumentPicker.getDocumentAsync({ copyToCacheDirectory: true });
    if (!r.canceled && r.assets?.[0]) {
      const a = r.assets[0];
      setTaskFile({ uri: a.uri, name: a.name, mimeType: a.mimeType ?? undefined });
    }
  };
  const driveFiles = useQuery<any[]>({
    queryKey: ["drive-files", driveSearch],
    queryFn: () => api(`/drive/files?q=${encodeURIComponent(driveSearch)}`),
    enabled: kind === "policy" && !!driveStatus.data?.connected && !driveFile,
  });

  if (user?.role !== "admin" && kind !== "task") {
    return <EmptyState icon="lock-closed-outline" title="Admins only" subtitle="Only admins and managers can post here." testID="compose-admin-only" />;
  }

  const submit = async () => {
    setError(null);
    if (!title.trim()) return setError(kind === "channel" ? "Enter a channel name." : "Enter a title.");
    let path = "";
    let payload: any = {};
    if (kind === "update") {
      if (!body.trim()) return setError("Write the update text.");
      path = "/updates";
      payload = { title, body, pinned };
    } else if (kind === "policy") {
      if (!body.trim()) return setError("Add the policy content.");
      path = "/policies";
      payload = { title, content: body, category, drive_file_id: driveFile?.id ?? null };
    } else if (kind === "event") {
      const iso = dmyToIso(date);
      if (!iso) return setError("Date must be DD-MM-YYYY.");
      path = "/events";
      payload = { title, description: body, date: iso, time, location };
    } else if (kind === "task") {
      if (isAdmin && !assignee && people.length === 0) return setError("Choose who this task is for.");
      const due = date ? dmyToIso(date) : "";
      if (due === null) return setError("Due date must be DD-MM-YYYY.");
      path = "/tasks";
      let attachmentId: string | null = null;
      if (taskFile) {
        setSaving(true);
        try {
          const up = await uploadForm(`${API_URL}/tasks/attachments`, { headers: authHeaders(), files: { file: taskFile } });
          const b = await up.json().catch(() => ({}));
          if (!up.ok) throw new Error(typeof b.detail === "string" ? b.detail : "Couldn't upload the file.");
          attachmentId = b.file_id;
        } catch (e: any) {
          setSaving(false);
          return setError(e.message || "Couldn't upload the file.");
        }
      }
      payload = {
        title,
        description: body,
        due_date: due,
        assignee_id: isAdmin && assignee ? assignee : "",
        assignee_ids: isAdmin && !assignee ? people : [],
        attachment_id: attachmentId,
      };
    } else {
      path = "/channels";
      payload = { name: title, description: body };
    }
    setSaving(true);
    try {
      await api(path, { method: "POST", body: payload });
      qc.invalidateQueries();
      toast(`${titleFor.split(" ").slice(-1)[0][0].toUpperCase()}${titleFor.split(" ").slice(-1)[0].slice(1)} saved`);
      router.back();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <KeyboardAwareScrollView
      style={styles.root}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 24 }}
      keyboardShouldPersistTaps="handled"
      bottomOffset={24}
      testID={`compose-${kind}-screen`}
    >
      <Stack.Screen options={{ title: titleFor }} />
      {kind === "policy" && (
        <View style={styles.chips}>
          {(["Policy", "Procedure"] as const).map((c) => (
            <Chip key={c} label={c} selected={category === c} onPress={() => setCategory(c)} testID={`compose-category-${c.toLowerCase()}`} />
          ))}
        </View>
      )}
      <Field
        label={kind === "channel" ? "Channel name" : "Title"}
        value={title}
        onChangeText={setTitle}
        placeholder={kind === "channel" ? "e.g. warehouse-team" : "Title"}
        autoCapitalize={kind === "channel" ? "none" : "sentences"}
        testID="compose-title-input"
      />
      {kind === "task" && isAdmin && (
        <View style={{ marginBottom: 16 }}>
          <Text style={styles.label}>Assign to</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
            {[
              { key: "all", label: "Everyone", icon: "people" as const },
              { key: user!.user_id, label: "Just me", icon: "lock-closed" as const },
            ].map((o) => (
              <Pressable
                key={o.key}
                testID={`compose-assignee-${o.key === "all" ? "all" : "me"}`}
                onPress={() => { setAssignee(o.key); setPeople([]); }}
                style={[styles.person, assignee === o.key && { borderColor: colors.brandPrimary, backgroundColor: colors.brandTertiary }]}
              >
                <View style={styles.optIcon}>
                  <Ionicons name={o.icon} size={18} color={colors.brandPrimary} />
                </View>
                <Text style={styles.personName} numberOfLines={1}>{o.label}</Text>
              </Pressable>
            ))}
            {(users.data ?? []).filter((u) => u.user_id !== user?.user_id).map((u) => (
              <Pressable
                key={u.user_id}
                testID={`compose-assignee-${u.user_id}`}
                onPress={() => togglePerson(u.user_id)}
                style={[styles.person, people.includes(u.user_id) && { borderColor: colors.brandPrimary, backgroundColor: colors.brandTertiary }]}
              >
                <Avatar name={u.name} picture={u.picture} size={36} />
                <Text style={styles.personName} numberOfLines={1}>{u.name.split(" ")[0]}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      )}
      {(kind === "event" || kind === "task") && (
        <>
          <Field label={kind === "event" ? "Date (DD-MM-YYYY)" : "Due date (DD-MM-YYYY)"} value={date} onChangeText={setDate} autoCapitalize="none" placeholder="e.g. 15-01-2027" testID="compose-date-input" />
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }} style={{ marginTop: -4, marginBottom: 16 }}>
            {[
              ["Tomorrow", 1],
              ["In 1 week", 7],
              ["In 2 weeks", 14],
              ["In 1 month", 30],
            ].map(([l, n]) => (
              <Chip key={l as string} label={l as string} selected={date === inDays(n as number)} onPress={() => setDate(inDays(n as number))} testID={`compose-date-quick-${n}`} />
            ))}
          </ScrollView>
        </>
      )}
      {kind === "event" && (
        <>
          <Field label="Time (optional)" value={time} onChangeText={setTime} placeholder="e.g. 14:00" testID="compose-time-input" />
          <Field label="Location (optional)" value={location} onChangeText={setLocation} placeholder="e.g. Main office" testID="compose-location-input" />
        </>
      )}
      <Field
        label={kind === "policy" ? "Content" : kind === "update" ? "Message" : "Description (optional)"}
        value={body}
        onChangeText={setBody}
        multiline
        placeholder="Write here..."
        testID="compose-body-input"
      />
      {kind === "policy" && driveStatus.data?.connected && (
        <View style={{ marginBottom: 16 }} testID="compose-drive-attach">
          <Text style={styles.label}>Attach a SharePoint file (optional)</Text>
          {driveFile ? (
            <View style={styles.driveSel}>
              <Ionicons name="logo-microsoft" size={18} color={colors.brandPrimary} />
              <Text style={styles.driveName} numberOfLines={1}>{driveFile.name}</Text>
              <Pressable testID="compose-drive-remove" onPress={() => setDriveFile(null)} hitSlop={10} style={styles.driveX}>
                <Ionicons name="close-circle" size={20} color={colors.muted} />
              </Pressable>
            </View>
          ) : (
            <>
              <TextInput
                testID="compose-drive-search"
                value={driveSearch}
                onChangeText={setDriveSearch}
                placeholder="Search Drive files"
                placeholderTextColor={colors.muted}
                style={styles.driveInput}
              />
              {driveFiles.isLoading ? (
                <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 8 }} />
              ) : (
                (driveFiles.data ?? []).slice(0, 6).map((f) => (
                  <Pressable key={f.id} testID={`compose-drive-file-${f.id}`} onPress={() => setDriveFile(f)} style={styles.driveRow}>
                    <Ionicons name="document-outline" size={18} color={colors.muted} />
                    <Text style={styles.driveName} numberOfLines={1}>{f.name}</Text>
                  </Pressable>
                ))
              )}
            </>
          )}
        </View>
      )}
      {kind === "task" && (
        <View style={{ marginBottom: 16 }} testID="compose-task-attach">
          <Text style={styles.label}>Attachment (optional)</Text>
          {taskFile ? (
            <View style={styles.driveSel}>
              <Ionicons name="document-attach-outline" size={18} color={colors.brandPrimary} />
              <Text style={styles.driveName} numberOfLines={1} testID="compose-task-file-name">{taskFile.name}</Text>
              <Pressable testID="compose-task-file-remove" onPress={() => setTaskFile(null)} hitSlop={10} style={styles.driveX}>
                <Ionicons name="close-circle" size={20} color={colors.muted} />
              </Pressable>
            </View>
          ) : (
            <Button label="Upload a file" variant="secondary" icon="attach" onPress={pickTaskFile} testID="compose-task-file-button" />
          )}
        </View>
      )}
      {kind === "update" && (
        <View style={styles.switchRow}>
          <Text style={styles.switchLabel}>Pin to top</Text>
          <Switch testID="compose-pinned-switch" value={pinned} onValueChange={setPinned} trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }} />
        </View>
      )}
      {kind === "task" && !isAdmin && <Text style={styles.hint}>Only you can see this task.</Text>}
      {kind === "task" && isAdmin && assignee === "all" && <Text style={styles.hint}>Every staff member gets their own copy to tick off.</Text>}
      {kind === "task" && isAdmin && people.length > 1 && (
        <Text style={styles.hint} testID="compose-collab-hint">{people.length} people selected. Each gets their own copy and can see who else is working on it.</Text>
      )}
      {kind !== "channel" && kind !== "task" && <Text style={styles.hint}>Everyone will get a notification.</Text>}
      {error && <Text style={styles.error} testID="compose-error">{error}</Text>}
      <Button label={kind === "task" && !isAdmin ? "Save task" : TITLES[kind]} loading={saving} onPress={submit} testID="compose-submit-button" />
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  chips: { flexDirection: "row", gap: 8, marginBottom: 16 },
  label: { fontSize: 13, fontWeight: "600", color: c.onSurfaceSecondary, marginBottom: 8 },
  person: { width: 76, alignItems: "center", gap: 4, padding: 8, borderRadius: 12, borderWidth: 1.5, borderColor: c.border, flexShrink: 0 },
  personName: { fontSize: 12, color: c.onSurface, fontWeight: "500" },
  optIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: c.brandTertiary, alignItems: "center", justifyContent: "center" },
  switchRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 16, minHeight: 44 },
  switchLabel: { fontSize: 16, color: c.onSurface },
  hint: { fontSize: 13, color: c.muted, marginBottom: 12 },
  error: { fontSize: 14, color: c.errorText, marginBottom: 12 },
  driveSel: { flexDirection: "row", alignItems: "center", gap: 10, paddingLeft: 14, borderRadius: 12, backgroundColor: c.brandTertiary, minHeight: 48 },
  driveName: { flex: 1, fontSize: 15, color: c.onSurface },
  driveX: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  driveInput: { minHeight: 48, borderRadius: 12, backgroundColor: c.surfaceSecondary, paddingHorizontal: 14, fontSize: 16, color: c.onSurface, marginBottom: 4 },
  driveRow: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 44, borderBottomWidth: 0.5, borderBottomColor: c.divider },
}));
