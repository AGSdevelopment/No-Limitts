import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { useQueryClient } from "@tanstack/react-query";

import { API_URL, api, authHeaders, getApiToken, openLink } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, Ionicons, timeAgo } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";
import { uploadForm } from "@/src/utils/upload";

const tokenQ = () => `token=${encodeURIComponent(getApiToken() ?? "")}`;

// "Add to calendar": Google Calendar link or a calendar file for Apple / Outlook.
export function AddToCalendar({ ev }: { ev: any }) {
  const styles = useStyles();
  const google = () => {
    const [y, m, day] = ev.date.split("-").map(Number);
    const ymd = (dt: Date) => dt.toISOString().slice(0, 10).replace(/-/g, "");
    const t = /^\s*(\d{1,2})(?:[:.](\d{2}))?\s*([ap])?\.?m?\.?\s*$/i.exec(ev.time ?? "");
    let dates: string;
    if (t) {
      let h = Number(t[1]);
      const min = Number(t[2] ?? 0);
      const ap = (t[3] ?? "").toLowerCase();
      if (ap === "p" && h < 12) h += 12;
      if (ap === "a" && h === 12) h = 0;
      const pad = (n: number) => String(n).padStart(2, "0");
      const endH = Math.min(h + 2, 23);
      dates = `${ymd(new Date(Date.UTC(y, m - 1, day)))}T${pad(h)}${pad(min)}00/${ymd(new Date(Date.UTC(y, m - 1, day)))}T${pad(endH)}${pad(min)}00`;
    } else {
      dates = `${ymd(new Date(Date.UTC(y, m - 1, day)))}/${ymd(new Date(Date.UTC(y, m - 1, day + 1)))}`;
    }
    const details = [ev.description, ev.catering && `Food & drink: ${ev.catering}`, ev.conditions].filter(Boolean).join("\n");
    const url = `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${encodeURIComponent(ev.title)}&dates=${dates}&details=${encodeURIComponent(details)}&location=${encodeURIComponent(ev.location ?? "")}&ctz=Australia/Perth`;
    openLink(url);
  };
  return (
    <View style={styles.calRow}>
      <Button label="Google" icon="logo-google" variant="secondary" onPress={google} style={{ flex: 1, paddingHorizontal: 8 }} testID="event-add-google" />
      <Button label="Apple/Outlook" icon="calendar-outline" variant="secondary" onPress={() => openLink(`${API_URL}/events/${ev.event_id}/ics?${tokenQ()}`)} style={{ flex: 1, paddingHorizontal: 8 }} testID="event-add-ics" />
    </View>
  );
}

// Photo gallery; people who went (or the organiser / admins) can add photos.
export function EventPhotos({ ev, canAdd, userId, isAdmin }: { ev: any; canAdd: boolean; userId?: string; isAdmin: boolean }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [uploading, setUploading] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const src = (p: any) => `${API_URL}/events/${ev.event_id}/photos/${p.photo_id}?${tokenQ()}`;

  const add = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7, allowsMultipleSelection: true, selectionLimit: 10 });
    if (r.canceled || !r.assets?.length) return;
    let ok = 0;
    for (const [i, a] of r.assets.entries()) {
      setUploading(r.assets.length - i);
      try {
        const res = await uploadForm(`${API_URL}/events/${ev.event_id}/photos`, {
          headers: authHeaders(),
          files: { file: { uri: a.uri, name: a.fileName ?? `photo-${i + 1}.jpg`, mimeType: a.mimeType ?? "image/jpeg" } },
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(typeof body.detail === "string" ? body.detail : "Upload failed");
        }
        ok += 1;
      } catch (e: any) {
        toast(e.message, "error");
        break;
      }
    }
    setUploading(0);
    if (ok) toast(`${ok} photo${ok > 1 ? "s" : ""} added`, "success");
    qc.invalidateQueries({ queryKey: ["event", ev.event_id] });
  };

  const remove = async (p: any) => {
    try {
      const res = await fetch(`${API_URL}/events/${ev.event_id}/photos/${p.photo_id}`, { method: "DELETE", headers: authHeaders() });
      if (!res.ok) throw new Error("Couldn't delete the photo");
      setOpen(null);
      qc.invalidateQueries({ queryKey: ["event", ev.event_id] });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const photos: any[] = ev.photos ?? [];
  const [photoText, setPhotoText] = useState("");
  const like = async (p: any) => {
    try {
      await api(`/events/${ev.event_id}/photos/${p.photo_id}/like`, { method: "POST" });
      qc.invalidateQueries({ queryKey: ["event", ev.event_id] });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const commentPhoto = async (p: any) => {
    try {
      await api(`/events/${ev.event_id}/photos/${p.photo_id}/comments`, { method: "POST", body: { text: photoText } });
      setPhotoText("");
      qc.invalidateQueries({ queryKey: ["event", ev.event_id] });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const selected = photos.find((p) => p.photo_id === open);
  return (
    <View style={styles.card} testID="event-photos">
      <Text style={styles.section}>Photos{photos.length ? ` · ${photos.length}` : ""}</Text>
      {photos.length === 0 && <Text style={styles.meta}>{canAdd ? "No photos yet. Add some so the team can relive it!" : "No photos yet."}</Text>}
      <View style={styles.grid}>
        {photos.map((p) => (
          <Pressable key={p.photo_id} onPress={() => setOpen(open === p.photo_id ? null : p.photo_id)} style={styles.thumbWrap} testID={`event-photo-${p.photo_id}`}>
            <Image source={{ uri: src(p) }} style={styles.thumb} contentFit="cover" transition={150} />
          </Pressable>
        ))}
      </View>
      {selected && (
        <View style={{ gap: 8 }} testID="event-photo-viewer">
          <Image source={{ uri: src(selected) }} style={styles.big} contentFit="contain" />
          <View style={styles.viewerRow}>
            <Pressable onPress={() => like(selected)} style={styles.likeBtn} accessibilityLabel="Like photo" testID="event-photo-like">
              <Ionicons name={selected.liked ? "heart" : "heart-outline"} size={22} color={selected.liked ? colors.error : colors.muted} />
              <Text style={styles.meta}>{selected.like_count}</Text>
            </Pressable>
            <Text style={[styles.meta, { flex: 1 }]}>Added by {selected.name}</Text>
            {(isAdmin || selected.user_id === userId) && (
              <Pressable onPress={() => remove(selected)} style={styles.iconBtn} accessibilityLabel="Delete photo" testID="event-photo-delete">
                <Ionicons name="trash-outline" size={20} color={colors.error} />
              </Pressable>
            )}
          </View>
          {selected.comments.map((c: any) => (
            <Text key={c.comment_id} style={styles.photoComment}>
              <Text style={{ fontWeight: "700" }}>{c.name} </Text>
              {c.text}
            </Text>
          ))}
          <View style={styles.viewerRow}>
            <TextInput value={photoText} onChangeText={setPhotoText} placeholder="Add a comment…" placeholderTextColor={colors.muted} style={styles.photoInput} testID="event-photo-comment-input" />
            <Pressable onPress={() => commentPhoto(selected)} disabled={!photoText.trim()} style={[styles.iconBtn, !photoText.trim() && { opacity: 0.4 }]} accessibilityLabel="Post comment" testID="event-photo-comment-send">
              <Ionicons name="send" size={20} color={colors.brandPrimary} />
            </Pressable>
          </View>
        </View>
      )}
      {canAdd && (
        <Button label={uploading ? `Uploading ${uploading}…` : "Add photos"} icon="images-outline" variant="secondary" loading={!!uploading} onPress={add} testID="event-photos-add" />
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  calRow: { flexDirection: "row", gap: 8 },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 16, gap: 10 },
  section: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  thumbWrap: { width: "32%", aspectRatio: 1, borderRadius: 10, overflow: "hidden", backgroundColor: c.surfaceSecondary },
  thumb: { width: "100%", height: "100%" },
  big: { width: "100%", aspectRatio: 1, borderRadius: 12, backgroundColor: c.surfaceSecondary },
  viewerRow: { flexDirection: "row", alignItems: "center" },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  likeBtn: { minWidth: 44, minHeight: 44, flexDirection: "row", alignItems: "center", gap: 4 },
  photoComment: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
  photoInput: { flex: 1, minHeight: 44, borderRadius: 12, backgroundColor: c.surfaceSecondary, paddingHorizontal: 12, fontSize: 16, color: c.onSurface },
}));

// Chat on the event page: lifts, food, plans.
export function EventComments({ ev, userId, isAdmin }: { ev: any; userId?: string; isAdmin: boolean }) {
  const styles = useCommentStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);

  const send = async () => {
    if (!text.trim()) return;
    setSending(true);
    try {
      await api(`/events/${ev.event_id}/comments`, { method: "POST", body: { text } });
      setText("");
      qc.invalidateQueries({ queryKey: ["event", ev.event_id] });
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSending(false);
    }
  };
  const remove = async (id: string) => {
    try {
      await api(`/events/${ev.event_id}/comments/${id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["event", ev.event_id] });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const comments: any[] = ev.comments ?? [];
  return (
    <View style={styles.card} testID="event-comments">
      <Text style={styles.section}>Chat{comments.length ? ` · ${comments.length}` : ""}</Text>
      {comments.length === 0 && <Text style={styles.meta}>Sort out lifts, food and plans here.</Text>}
      {comments.map((c) => (
        <View key={c.comment_id} style={styles.row} testID={`event-comment-${c.comment_id}`}>
          <Avatar name={c.name} picture={c.picture} size={32} />
          <View style={styles.bubble}>
            <Text style={styles.name}>
              {c.name} <Text style={styles.meta}>· {timeAgo(c.created_at)}</Text>
            </Text>
            <Text style={styles.text}>{c.text}</Text>
          </View>
          {(isAdmin || c.user_id === userId) && (
            <Pressable onPress={() => remove(c.comment_id)} style={styles.iconBtn} accessibilityLabel="Delete message" testID={`event-comment-delete-${c.comment_id}`}>
              <Ionicons name="trash-outline" size={18} color={colors.muted} />
            </Pressable>
          )}
        </View>
      ))}
      <View style={styles.inputRow}>
        <TextInput value={text} onChangeText={setText} placeholder="Write a message…" placeholderTextColor={colors.muted} style={styles.input} multiline testID="event-comment-input" />
        <Pressable onPress={send} disabled={sending || !text.trim()} style={[styles.send, (sending || !text.trim()) && { opacity: 0.5 }]} accessibilityLabel="Send message" testID="event-comment-send">
          <Ionicons name="send" size={18} color={colors.onBrandPrimary} />
        </Pressable>
      </View>
    </View>
  );
}

const useCommentStyles = makeStyles((c) => ({
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 16, gap: 10 },
  section: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 12, color: c.muted, fontWeight: "400" },
  row: { flexDirection: "row", gap: 8, alignItems: "flex-start" },
  bubble: { flex: 1, backgroundColor: c.surfaceSecondary, borderRadius: 12, padding: 10, gap: 2 },
  name: { fontSize: 13, fontWeight: "700", color: c.onSurface },
  text: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  inputRow: { flexDirection: "row", gap: 8, alignItems: "flex-end" },
  input: { flex: 1, minHeight: 44, maxHeight: 120, borderRadius: 12, backgroundColor: c.surfaceSecondary, paddingHorizontal: 12, paddingVertical: 10, fontSize: 16, color: c.onSurface },
  send: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.brandPrimary, alignItems: "center", justifyContent: "center" },
}));
