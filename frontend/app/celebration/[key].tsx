// Celebration wall: congratulations messages + photos for one birthday / work anniversary.
import { useState } from "react";
import { Pressable, RefreshControl, View } from "react-native";
import { Text, TextInput } from "@/src/components/text";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { LinearGradient } from "expo-linear-gradient";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders, getApiToken } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, ErrorState, Ionicons, Loading, timeAgo } from "@/src/components/ui";
import { uploadForm } from "@/src/utils/upload";
import { makeStyles, useTheme } from "@/src/theme";

export default function CelebrationWall() {
  const { key } = useLocalSearchParams<{ key: string }>();
  const { user } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useQuery<any>({ queryKey: ["celebration", key], queryFn: () => api(`/celebrations/${key}`) });
  const [text, setText] = useState("");
  const [photo, setPhoto] = useState<ImagePicker.ImagePickerAsset | null>(null);
  const [posting, setPosting] = useState(false);

  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) return <ErrorState message={(q.error as any)?.message ?? "Couldn't load this celebration"} onRetry={q.refetch} />;
  const c = q.data;
  const first = (c.name || "").split(" ")[0];
  const isMe = c.user_id === user?.user_id;
  const title = c.type === "birthday"
    ? (isMe ? "Your birthday wall" : `${first}'s birthday`)
    : (isMe ? `Your ${c.years}-year anniversary` : `${first}'s ${c.years}-year anniversary`);

  const pick = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7 });
    if (!r.canceled && r.assets?.[0]) setPhoto(r.assets[0]);
  };

  const post = async () => {
    if (!text.trim() && !photo) return;
    setPosting(true);
    try {
      const res = await uploadForm(`${API_URL}/celebrations/${key}/posts`, {
        headers: authHeaders(),
        fields: { text: text.trim() },
        files: photo ? { file: { uri: photo.uri, name: photo.fileName ?? "photo.jpg", mimeType: photo.mimeType ?? "image/jpeg" } } : {},
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(typeof body.detail === "string" ? body.detail : "Couldn't post your message");
      }
      setText("");
      setPhoto(null);
      toast("Posted 🎉", "success");
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setPosting(false);
    }
  };

  const remove = async (p: any) => {
    try {
      await api(`/celebrations/${key}/posts/${p.post_id}`, { method: "DELETE" });
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const message = async () => {
    try {
      const conv = await api("/dms", { method: "POST", body: { user_id: c.user_id } });
      router.push({ pathname: "/chat/[id]", params: { id: conv.conversation_id, name: c.name } });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <View style={styles.root} testID="celebration-wall">
      <Stack.Screen options={{ title: c.type === "birthday" ? "Birthday wall" : "Anniversary wall" }} />
      <KeyboardAwareScrollView bottomOffset={16} contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}>
        <View style={styles.hero}>
          <LinearGradient colors={c.type === "birthday" ? [colors.accent, colors.brandPrimary] : [colors.brandPrimary, colors.accent]}
            start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }} />
          <Avatar name={c.name} picture={c.picture} size={56} />
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={styles.heroTitle} testID="celebration-title">{title} {c.type === "birthday" ? "🎂" : "🎉"}</Text>
            <Text style={styles.heroSub}>{c.posts.length ? `${c.posts.length} message${c.posts.length > 1 ? "s" : ""} from the team` : isMe ? "Messages from the team will appear here" : "Be the first to say congratulations!"}</Text>
          </View>
          <View style={styles.treeWrap}>
            <Image source={require("@/assets/images/brand-mark.png")} style={{ width: "100%", height: "100%" }} contentFit="contain" />
          </View>
        </View>

        <View style={styles.card} testID="celebration-composer">
          <TextInput value={text} onChangeText={setText} placeholder={isMe ? "Say thanks to the team…" : `Write something for ${first}…`}
            placeholderTextColor={colors.muted} multiline maxLength={1000} style={styles.input} testID="celebration-input" />
          {photo && (
            <View>
              <Image source={{ uri: photo.uri }} style={styles.preview} contentFit="cover" />
              <Pressable onPress={() => setPhoto(null)} style={styles.removePhoto} accessibilityLabel="Remove photo" testID="celebration-photo-remove">
                <Ionicons name="close" size={18} color="#FFFFFF" />
              </Pressable>
            </View>
          )}
          <View style={styles.row}>
            <Button label={photo ? "Change photo" : "Add photo"} icon="image-outline" variant="secondary" onPress={pick} style={{ flex: 1 }} testID="celebration-add-photo" />
            <Button label="Post" icon="send" loading={posting} disabled={!text.trim() && !photo} onPress={post} style={{ flex: 1 }} testID="celebration-post" />
          </View>
          {!isMe && <Button label={`Send ${first} a private message`} icon="chatbubble-ellipses-outline" variant="ghost" onPress={message} testID="celebration-dm" />}
        </View>

        {c.posts.map((p: any) => (
          <View key={p.post_id} style={styles.card} testID={`celebration-post-${p.post_id}`}>
            <View style={styles.row}>
              <Avatar name={p.name} picture={p.picture} size={36} />
              <View style={{ flex: 1 }}>
                <Text style={styles.author}>{p.name}</Text>
                <Text style={styles.meta}>{timeAgo(p.created_at)}</Text>
              </View>
              {p.can_delete && (
                <Pressable onPress={() => remove(p)} style={styles.iconBtn} accessibilityLabel="Delete message" testID={`celebration-delete-${p.post_id}`}>
                  <Ionicons name="trash-outline" size={20} color={colors.error} />
                </Pressable>
              )}
            </View>
            {!!p.text && <Text style={styles.body}>{p.text}</Text>}
            {p.has_photo && (
              <Image source={{ uri: `${API_URL}/celebrations/${key}/posts/${p.post_id}/photo?token=${encodeURIComponent(getApiToken() ?? "")}` }}
                style={styles.photo} contentFit="cover" transition={200} />
            )}
          </View>
        ))}
      </KeyboardAwareScrollView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  hero: { flexDirection: "row", alignItems: "center", gap: 12, borderRadius: 20, overflow: "hidden", padding: 16, minHeight: 110 },
  heroTitle: { fontSize: 20, fontWeight: "800", color: "#FFFFFF" },
  heroSub: { fontSize: 13, fontWeight: "600", color: "#FFFFFF", opacity: 0.92 },
  treeWrap: { width: 64, height: 64, borderRadius: 32, backgroundColor: c.surface, padding: 6 },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 14, gap: 10 },
  input: { minHeight: 80, fontSize: 15, color: c.onSurface, backgroundColor: c.surfaceSecondary, borderRadius: 12, padding: 12, textAlignVertical: "top" },
  preview: { width: "100%", height: 180, borderRadius: 12 },
  removePhoto: { position: "absolute", top: 8, right: 8, width: 32, height: 32, borderRadius: 16, backgroundColor: "rgba(0,0,0,0.55)", alignItems: "center", justifyContent: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  author: { fontSize: 15, fontWeight: "700", color: c.onSurface },
  meta: { fontSize: 12, color: c.muted },
  body: { fontSize: 15, color: c.onSurface, lineHeight: 21 },
  photo: { width: "100%", aspectRatio: 4 / 3, borderRadius: 12, backgroundColor: c.surfaceSecondary },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
}));
