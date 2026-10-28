import { useMemo, useState } from "react";
import { FlatList, KeyboardAvoidingView, Linking, Modal, Platform, Pressable, RefreshControl, ScrollView, Text, TextInput, View } from "react-native";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken, openLink } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/toast";
import { Button, Chip, ConfirmSheet, EmptyState, ErrorState, Ionicons, Loading, Pill } from "@/src/components/ui";
import { CAT_ICON, DirSpace, SPACE_LABEL } from "@/src/directory";
import { makeStyles, useTheme } from "@/src/theme";

export function openDirectoryFile(entryId: string, fileId: string) {
  return openLink(`${API_URL}/directory/${entryId}/files/${fileId}?token=${encodeURIComponent(getApiToken() ?? "")}`);
}

export default function Directory() {
  const { space, category } = useLocalSearchParams<{ space: DirSpace; category: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [removing, setRemoving] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const q = useQuery<any[]>({
    queryKey: ["directory", space, category],
    queryFn: () => api(`/directory?space=${space}&category=${encodeURIComponent(category)}`),
  });

  const [postcode, setPostcode] = useState("");
  const [radius, setRadius] = useState<number | null>(10);
  const pcOf = (e: any) => (`${e.address ?? ""}`.match(/\b(\d{4})\b/) ?? [])[1];
  const list = useMemo(() => {
    const s = search.trim().toLowerCase();
    let out = (q.data ?? []).filter((e) => !s || `${e.name} ${e.services ?? ""} ${e.contact} ${e.address} ${e.note}`.toLowerCase().includes(s));
    if (/^\d{4}$/.test(postcode)) {
      const target = Number(postcode);
      const dist = (e: any) => (pcOf(e) ? Math.abs(Number(pcOf(e)) - target) : Infinity);
      out = out.filter((e) => radius === null || dist(e) <= radius).sort((a, b) => dist(a) - dist(b));
    }
    return out;
  }, [q.data, search, postcode, radius]);

  const remove = async () => {
    setBusy(true);
    try {
      await api(`/directory/${removing.entry_id}`, { method: "DELETE" });
      qc.invalidateQueries({ queryKey: ["directory", space, category] });
      qc.invalidateQueries({ queryKey: ["directory-highlights"] });
      toast(`${removing.name} removed`, "info");
      setRemoving(null);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const approve = async (e: any) => {
    try {
      await api(`/directory/${e.entry_id}/approve`, { method: "POST" });
      qc.invalidateQueries({ queryKey: ["directory", space, category] });
      toast(`${e.name} approved`, "success");
    } catch (err: any) {
      toast(err.message, "error");
    }
  };

  const isReferral = category === "Trusted Referral Partner Organisations";
  const title = isReferral ? "Referral Partners" : `${SPACE_LABEL[space] ?? ""} · ${category}`;
  const rateable = category === "Suppliers" || category === "Activities";
  const shareable = isReferral || rateable;
  const [picking, setPicking] = useState(false);
  const [review, setReview] = useState<{ item: any; stars: number; comment: string } | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const channel = useQuery<any>({ queryKey: ["referral-share-channel"], queryFn: () => api("/directory/share-channel"), enabled: shareable });
  const channels = useQuery<any[]>({ queryKey: ["conversations"], queryFn: () => api("/conversations"), enabled: picking });

  const [sharing, setSharing] = useState<string | null>(null);
  const share = async (e: any) => {
    if (sharing) return;
    setSharing(e.entry_id);
    try {
      const r = await api(`/directory/${e.entry_id}/share`, { method: "POST" });
      toast(`Shared to #${r.channel}`, "success");
    } catch (err: any) {
      toast(err.message, "error");
    } finally {
      setSharing(null);
    }
  };
  const saveReview = async () => {
    if (!review) return;
    setReviewBusy(true);
    try {
      await api(`/directory/${review.item.entry_id}/rate`, { method: "POST", body: { stars: review.stars, comment: review.comment } });
      qc.invalidateQueries({ queryKey: ["directory", space, category] });
      qc.invalidateQueries({ queryKey: ["directory-latest-reviews"] });
      toast("Thanks for your review", "success");
      setReview(null);
    } catch (err: any) {
      toast(err.message, "error");
    } finally {
      setReviewBusy(false);
    }
  };
  const chooseChannel = async (id: string) => {
    try {
      await api("/directory/share-channel", { method: "PUT", body: { conversation_id: id } });
      channel.refetch();
      setPicking(false);
    } catch (err: any) {
      toast(err.message, "error");
    }
  };

  return (
    <View style={styles.root} testID="directory-screen">
      <Stack.Screen
        options={{
          title,
          headerRight: isAdmin || isReferral
            ? () => (
                <Pressable testID="directory-add-button" onPress={() => router.push({ pathname: "/directory-new", params: { space, category } })} hitSlop={10} style={styles.headerBtn} accessibilityLabel={isAdmin ? "Add" : "Suggest"}>
                  <Ionicons name="add-circle" size={24} color={colors.brandPrimary} />
                  <Text style={styles.headerText}>{isAdmin ? "Add" : "Suggest"}</Text>
                </Pressable>
              )
            : undefined,
        }}
      />
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Couldn't load this list." onRetry={() => q.refetch()} />
      ) : (
        <FlatList
          data={list}
          keyExtractor={(e) => e.entry_id}
          contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
          ListHeaderComponent={
            <View style={{ gap: 10 }}>
              {shareable && !channel.isLoading && (
                <View style={styles.shareBar} testID="directory-share-channel">
                  <Ionicons name="chatbubbles-outline" size={18} color={colors.brandPrimary} />
                  <Text style={[styles.sub, { flex: 1 }]}>{channel.data ? `Shares go to #${channel.data.name}` : isAdmin ? "Choose the channel shares go to" : "An admin needs to choose the sharing channel"}</Text>
                  {isAdmin && (
                    <Pressable onPress={() => setPicking(true)} style={styles.linkBtn} testID="directory-share-channel-change">
                      <Text style={styles.link}>{channel.data ? "Change" : "Choose"}</Text>
                    </Pressable>
                  )}
                </View>
              )}
              {rateable && (q.data?.length ?? 0) > 1 && <Text style={styles.sub}>Sorted by the team&apos;s star ratings</Text>}
              {isReferral && (q.data?.length ?? 0) > 0 && (
                <View style={{ gap: 8 }} testID="directory-postcode-filter">
                  <TextInput
                    value={postcode}
                    onChangeText={(t) => setPostcode(t.replace(/\D/g, "").slice(0, 4))}
                    placeholder="Participant's postcode, e.g. 6027"
                    placeholderTextColor={colors.muted}
                    keyboardType="number-pad"
                    style={styles.search}
                    testID="directory-postcode-input"
                  />
                  {postcode.length === 4 && (
                    <View style={styles.actions}>
                      {[
                        { label: "Same postcode", v: 0 },
                        { label: "Nearby (±10)", v: 10 },
                        { label: "Wider (±50)", v: 50 },
                        { label: "All, nearest first", v: null },
                      ].map((r) => (
                        <Chip key={r.label} label={r.label} selected={radius === r.v} onPress={() => setRadius(r.v)} testID={`directory-radius-${r.v ?? "all"}`} />
                      ))}
                    </View>
                  )}
                  {postcode.length === 4 && <Text style={styles.sub}>Matched on the postcode in each partner&apos;s location. Close postcode numbers are usually nearby areas.</Text>}
                </View>
              )}
              {(q.data?.length ?? 0) > 3 && (
                <TextInput value={search} onChangeText={setSearch} placeholder={`Search ${category.toLowerCase()}`} placeholderTextColor={colors.muted} style={styles.search} testID="directory-search" />
              )}
            </View>
          }
          ListEmptyComponent={
            <EmptyState
              icon={CAT_ICON[category] ?? "folder-open-outline"}
              title={search ? "No matches" : `No ${category.toLowerCase()} yet`}
              subtitle={search ? undefined : isAdmin ? "Tap Add to put the first one here." : isReferral ? "Tap Suggest to recommend one for an admin to approve." : "Admins can add entries here."}
              testID="directory-empty"
            />
          }
          renderItem={({ item }) => (
            <View style={styles.card} testID={`directory-entry-${item.entry_id}`}>
              <View style={styles.row}>
                <Ionicons name={CAT_ICON[category] ?? "folder-outline"} size={22} color={colors.brandPrimary} />
                <Text style={[styles.name, { flex: 1 }]}>{item.name}</Text>
                {isAdmin && (
                  <>
                    <Pressable onPress={() => router.push({ pathname: "/directory-new", params: { edit: item.entry_id } })} style={styles.iconBtn} accessibilityLabel="Edit" testID={`directory-edit-${item.entry_id}`}>
                      <Ionicons name="create-outline" size={20} color={colors.muted} />
                    </Pressable>
                    <Pressable onPress={() => setRemoving(item)} style={styles.iconBtn} accessibilityLabel="Remove" testID={`directory-delete-${item.entry_id}`}>
                      <Ionicons name="trash-outline" size={20} color={colors.muted} />
                    </Pressable>
                  </>
                )}
              </View>
              {!!item.services && <Text style={styles.note}><Text style={styles.bold}>Services: </Text>{item.services}</Text>}
              {!!item.contact && <Text style={styles.sub}>Contact: {item.contact}</Text>}
              {!!item.address && <Text style={styles.sub}>📍 {item.address}</Text>}
              {!!item.note && <Text style={styles.note}>{item.note}</Text>}
              {rateable && (
                <View style={styles.row} testID={`directory-rating-${item.entry_id}`}>
                  <View style={styles.stars}>
                    {[1, 2, 3, 4, 5].map((n) => (
                      <Pressable key={n} onPress={() => setReview({ item, stars: n, comment: item.my_comment ?? "" })} style={styles.star} accessibilityLabel={`Rate ${n} star${n > 1 ? "s" : ""}`} testID={`directory-star-${item.entry_id}-${n}`}>
                        <Ionicons name={n <= item.my_rating ? "star" : "star-outline"} size={24} color={colors.warning} />
                      </Pressable>
                    ))}
                  </View>
                  <Text style={styles.sub}>{item.rating_count ? `${item.avg_rating} ★ · ${item.rating_count} rating${item.rating_count > 1 ? "s" : ""}` : "Be the first to rate"}</Text>
                </View>
              )}
              {rateable && item.reviews?.length > 0 && (
                <View style={{ gap: 6 }} testID={`directory-reviews-${item.entry_id}`}>
                  {(expanded === item.entry_id ? item.reviews : item.reviews.slice(0, 2)).map((r: any, i: number) => (
                    <View key={`${r.name}${i}`} style={styles.review}>
                      <Text style={styles.reviewHead}>{"★".repeat(r.stars)} {r.name}</Text>
                      <Text style={styles.note}>{r.text}</Text>
                    </View>
                  ))}
                  {item.reviews.length > 2 && (
                    <Pressable onPress={() => setExpanded(expanded === item.entry_id ? null : item.entry_id)} style={styles.linkBtn} testID={`directory-reviews-toggle-${item.entry_id}`}>
                      <Text style={styles.link}>{expanded === item.entry_id ? "Show fewer" : `See all ${item.reviews.length} reviews`}</Text>
                    </Pressable>
                  )}
                </View>
              )}
              {item.status === "pending" && (
                <View style={styles.pendingBox} testID={`directory-pending-${item.entry_id}`}>
                  <Pill label="Waiting for admin approval" tone="accent" />
                  <Text style={styles.sub}>Suggested by {item.created_by}</Text>
                  {isAdmin && (
                    <View style={{ flexDirection: "row", gap: 8 }}>
                      <Button label="Approve" icon="checkmark" onPress={() => approve(item)} style={{ flex: 1 }} testID={`directory-approve-${item.entry_id}`} />
                      <Button label="Reject" variant="ghost" onPress={() => setRemoving(item)} style={{ flex: 1 }} testID={`directory-reject-${item.entry_id}`} />
                    </View>
                  )}
                </View>
              )}
              <View style={styles.actions}>
                {shareable && item.status !== "pending" && <Action icon="share-social-outline" label={sharing === item.entry_id ? "Sharing…" : "Share to chat"} onPress={() => share(item)} testID={`directory-share-${item.entry_id}`} />}
                {category === "Activities" && (
                  <Action
                    icon="calendar-outline"
                    label="Make it a team event"
                    onPress={() => router.push({ pathname: "/event-new", params: { title: item.name, location: item.address || "", description: [item.note, item.link].filter(Boolean).join("\n") } })}
                    testID={`directory-event-${item.entry_id}`}
                  />
                )}
                {!!item.phone && <Action icon="call-outline" label={item.phone} onPress={() => Linking.openURL(`tel:${item.phone.replace(/\s/g, "")}`)} testID={`directory-phone-${item.entry_id}`} />}
                {!!item.email && <Action icon="mail-outline" label="Email" onPress={() => Linking.openURL(`mailto:${item.email}`)} testID={`directory-email-${item.entry_id}`} />}
                {!!item.link && <Action icon="open-outline" label="Website" onPress={() => openLink(item.link)} testID={`directory-link-${item.entry_id}`} />}
              </View>
              {item.files.map((f: any) => (
                <Pressable key={f.file_id} onPress={() => openDirectoryFile(item.entry_id, f.file_id)} style={styles.file} testID={`directory-file-${f.file_id}`}>
                  <Ionicons name="document-attach-outline" size={18} color={colors.accent} />
                  <Text style={styles.fileName} numberOfLines={1}>{f.name}</Text>
                  <Ionicons name="open-outline" size={16} color={colors.muted} />
                </Pressable>
              ))}
            </View>
          )}
        />
      )}
      <Modal visible={!!review} transparent animationType="slide" onRequestClose={() => setReview(null)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <Pressable style={styles.scrim} onPress={() => setReview(null)} />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID="directory-review-sheet">
          <Text style={styles.name}>Rate {review?.item.name}</Text>
          <View style={styles.stars}>
            {[1, 2, 3, 4, 5].map((n) => (
              <Pressable key={n} onPress={() => review && setReview({ ...review, stars: n })} style={styles.star} accessibilityLabel={`${n} star${n > 1 ? "s" : ""}`} testID={`directory-review-star-${n}`}>
                <Ionicons name={review && n <= review.stars ? "star" : "star-outline"} size={30} color={colors.warning} />
              </Pressable>
            ))}
          </View>
          <TextInput
            value={review?.comment ?? ""}
            onChangeText={(t) => review && setReview({ ...review, comment: t.slice(0, 300) })}
            placeholder="Why is it great? (optional)"
            placeholderTextColor={colors.muted}
            multiline
            style={[styles.search, styles.reviewInput]}
            testID="directory-review-comment"
          />
          <Text style={styles.sub}>{(review?.comment ?? "").length}/300</Text>
          <Button label="Save review" icon="checkmark" loading={reviewBusy} onPress={saveReview} testID="directory-review-save" />
          <Button label="Cancel" variant="ghost" onPress={() => setReview(null)} testID="directory-review-cancel" />
        </View>
        </KeyboardAvoidingView>
      </Modal>
      <Modal visible={picking} transparent animationType="slide" onRequestClose={() => setPicking(false)}>
        <Pressable style={styles.scrim} onPress={() => setPicking(false)} />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID="directory-channel-sheet">
          <Text style={styles.name}>Share to</Text>
          <Button label="Close" variant="ghost" onPress={() => setPicking(false)} testID="directory-channel-close" />
          {channels.isLoading ? (
            <Loading />
          ) : (
            <ScrollView style={{ maxHeight: 360 }}>
              {(channels.data ?? []).filter((c) => c.type === "channel").map((c) => (
                <Pressable key={c.conversation_id} onPress={() => chooseChannel(c.conversation_id)} style={styles.channelRow} testID={`directory-channel-${c.conversation_id}`}>
                  <Text style={styles.note}>#{c.name}</Text>
                  {channel.data?.conversation_id === c.conversation_id && <Ionicons name="checkmark" size={20} color={colors.brandPrimary} />}
                </Pressable>
              ))}
            </ScrollView>
          )}
        </View>
      </Modal>
      <ConfirmSheet
        visible={!!removing}
        title={`Remove ${removing?.name ?? ""}?`}
        message="This removes the entry and its files for everyone."
        confirmLabel="Remove"
        loading={busy}
        onConfirm={remove}
        onClose={() => setRemoving(null)}
      />
    </View>
  );
}

function Action({ icon, label, onPress, testID }: { icon: any; label: string; onPress: () => void; testID: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <Pressable onPress={onPress} style={styles.action} testID={testID}>
      <Ionicons name={icon} size={16} color={colors.brandPrimary} />
      <Text style={styles.actionText} numberOfLines={1}>{label}</Text>
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  headerBtn: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 44, paddingHorizontal: 8 },
  headerText: { fontSize: 15, fontWeight: "700", color: c.brandPrimary },
  search: { minHeight: 44, borderRadius: 12, backgroundColor: c.surface, paddingHorizontal: 12, fontSize: 16, color: c.onSurface, marginBottom: 4 },
  card: { backgroundColor: c.surface, borderRadius: 16, padding: 14, gap: 6 },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  name: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  note: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  action: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, paddingHorizontal: 12, borderRadius: 20, backgroundColor: c.brandTertiary, maxWidth: 220 },
  actionText: { fontSize: 13, fontWeight: "600", color: c.brandPrimary, flexShrink: 1 },
  file: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 44, paddingHorizontal: 10, borderRadius: 10, backgroundColor: c.surfaceSecondary },
  fileName: { flex: 1, fontSize: 14, color: c.onSurface },
  shareBar: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: c.surface, borderRadius: 12, paddingLeft: 12, minHeight: 48 },
  linkBtn: { minHeight: 44, paddingHorizontal: 12, justifyContent: "center" },
  link: { fontSize: 14, fontWeight: "700", color: c.brandPrimary },
  stars: { flexDirection: "row" },
  bold: { fontWeight: "700" },
  pendingBox: { gap: 6, padding: 10, borderRadius: 12, backgroundColor: c.surfaceSecondary },
  reviewInput: { minHeight: 88, textAlignVertical: "top", paddingTop: 10, borderWidth: 1, borderColor: c.borderStrong, backgroundColor: c.surfaceSecondary },
  review: { backgroundColor: c.surfaceSecondary, borderRadius: 10, padding: 10, gap: 2 },
  reviewHead: { fontSize: 12, fontWeight: "700", color: c.warningText },
  star: { width: 40, height: 44, alignItems: "center", justifyContent: "center" },
  scrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 16, gap: 8 },
  channelRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 48, borderBottomWidth: 1, borderBottomColor: c.border },
}));
