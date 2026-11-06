// Shift swaps and the open shift board: offers to me, swaps for Rosters to approve, open shifts to claim, and the offer sheet.
import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/src/api";
import { Text, TextInput } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Sheet } from "@/src/components/participant-sheets";
import { Button, Chip, Ionicons, Loading } from "@/src/components/ui";
import { when } from "@/src/components/shift-sheets";
import { makeStyles, useTheme } from "@/src/theme";

export function OffersPanel({ onChanged }: { onChanged?: () => void }) {
  const styles = useStyles();
  const toast = useToast();
  const q = useQuery<any>({ queryKey: ["shift-offers"], queryFn: () => api("/shifts-offers") });
  const [busy, setBusy] = useState("");
  const run = async (id: string, path: string, body: any, ok: string) => {
    setBusy(id + path);
    try {
      await api(`/shifts/${id}/${path}`, { method: "POST", body });
      toast(ok, "success");
      q.refetch();
      onChanged?.();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy("");
    }
  };
  if (q.isLoading) return <Loading />;
  const d = q.data ?? { offers: [], approvals: [], open: [] };
  return (
    <View style={{ gap: 12 }} testID="offers-panel">
      {!!d.approvals.length && <Text style={styles.section}>Swaps to approve</Text>}
      {d.approvals.map((s: any) => (
        <View key={s.shift_id} style={styles.card} testID={`swap-approval-${s.shift_id}`}>
          <Text style={styles.title}>{s.participant_name}</Text>
          <Text style={styles.body}>{when(s)}</Text>
          <Text style={styles.meta}>{s.worker_name} → {s.swap.to_name}{s.swap.note ? ` · “${s.swap.note}”` : ""}</Text>
          <View style={styles.row}>
            <Button label="Approve" icon="checkmark" style={{ flex: 1 }} loading={busy === s.shift_id + "swap/decide"}
              onPress={() => run(s.shift_id, "swap/decide", { approve: true }, "Swap approved")} testID={`swap-approve-${s.shift_id}`} />
            <Button label="Reject" variant="secondary" style={{ flex: 1 }}
              onPress={() => run(s.shift_id, "swap/decide", { approve: false }, "Swap rejected")} testID={`swap-reject-${s.shift_id}`} />
          </View>
        </View>
      ))}
      <Text style={styles.section}>Shifts offered to you</Text>
      {!d.offers.length && <Text style={styles.meta}>No swap offers right now.</Text>}
      {d.offers.map((s: any) => (
        <View key={s.shift_id} style={styles.card} testID={`swap-offer-${s.shift_id}`}>
          <Text style={styles.title}>{s.participant_name}</Text>
          <Text style={styles.body}>{when(s)}</Text>
          <Text style={styles.meta}>From {s.swap.from_name}{s.swap.note ? ` · “${s.swap.note}”` : ""}. Rosters approve once you accept.</Text>
          <View style={styles.row}>
            <Button label="Take it" icon="checkmark" style={{ flex: 1 }} loading={busy === s.shift_id + "swap/respond"}
              onPress={() => run(s.shift_id, "swap/respond", { accept: true }, "Sent to Rosters for approval")} testID={`swap-accept-${s.shift_id}`} />
            <Button label="No thanks" variant="secondary" style={{ flex: 1 }}
              onPress={() => run(s.shift_id, "swap/respond", { accept: false }, "Offer declined")} testID={`swap-decline-${s.shift_id}`} />
          </View>
        </View>
      ))}
      <Text style={styles.section}>Open shifts</Text>
      {!d.open.length && <Text style={styles.meta}>No open shifts for your participants.</Text>}
      {d.open.map((s: any) => (
        <View key={s.shift_id} style={styles.card} testID={`open-shift-${s.shift_id}`}>
          <Text style={styles.title}>{s.participant_name}</Text>
          <Text style={styles.body}>{when(s)}</Text>
          {s.can_claim ? (
            <Button label="Claim shift" icon="hand-left-outline" loading={busy === s.shift_id + "claim"}
              onPress={() => run(s.shift_id, "claim", {}, "Shift is yours! It's on your roster.")} testID={`open-claim-${s.shift_id}`} />
          ) : <Text style={styles.meta}>Waiting for a Support Team member to claim it.</Text>}
        </View>
      ))}
    </View>
  );
}

export function SwapSheet({ shift, onClose, onDone }: { shift: any; onClose: () => void; onDone: () => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const team = useQuery<any[]>({ queryKey: ["teammates", shift?.shift_id], queryFn: () => api(`/shifts/${shift.shift_id}/teammates`), enabled: !!shift });
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (shift) { setTo(""); setNote(""); } }, [shift]);
  const save = async () => {
    setBusy(true);
    try {
      await api(`/shifts/${shift.shift_id}/swap`, { method: "POST", body: { to_worker_id: to, note } });
      toast("Offer sent to your teammate", "success");
      onDone();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet visible={!!shift} onClose={() => !busy && onClose()} title="Offer this shift to a teammate"
      sub={shift ? `${shift.participant_name} · ${when(shift)}. They accept, then Rosters approve.` : ""} testID="swap-sheet">
      {team.isLoading ? <Loading /> : (
        <View style={styles.chips}>
          {(team.data ?? []).map((w) => (
            <Chip key={w.user_id} label={w.name} selected={to === w.user_id} onPress={() => setTo(w.user_id)} testID={`swap-to-${w.user_id}`} />
          ))}
          {!team.data?.length && <Text style={styles.meta}>No one else is on this participant&apos;s Support Team yet.</Text>}
        </View>
      )}
      <TextInput value={note} onChangeText={setNote} placeholder="Note for your teammate (optional)" placeholderTextColor={colors.muted}
        maxLength={300} style={styles.input} testID="swap-note" />
      <Button label="Send offer" icon="swap-horizontal-outline" loading={busy} disabled={busy || !to} onPress={save} testID="swap-send" />
      <Button label="Cancel" variant="ghost" onPress={onClose} />
    </Sheet>
  );
}

export function SwapStatus({ s }: { s: any }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const st = s.swap?.status;
  if (!st || ["approved"].includes(st)) return null;
  const text: Record<string, string> = {
    pending_teammate: `Offered to ${s.swap.to_name}, waiting for them`, pending_rosters: `${s.swap.to_name} accepted, waiting for Rosters`,
    declined_by_teammate: `${s.swap.to_name} declined the swap`, rejected: "Swap not approved by Rosters", withdrawn: "Swap offer withdrawn",
  };
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }} testID={`swap-status-${s.shift_id}`}>
      <Ionicons name="swap-horizontal-outline" size={16} color={colors.brandPrimary} />
      <Text style={styles.swap}>{text[st] ?? st}</Text>
    </View>
  );
}

export function OfferLink({ onPress, testID }: { onPress: () => void; testID: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <Pressable onPress={onPress} style={styles.link} testID={testID}>
      <Ionicons name="swap-horizontal-outline" size={16} color={colors.brandPrimary} />
      <Text style={styles.linkText}>Offer to a teammate</Text>
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  section: { fontSize: 13, fontWeight: "800", color: c.onSurface, textTransform: "uppercase" },
  card: { backgroundColor: c.surface, borderRadius: 14, padding: 14, gap: 6 },
  row: { flexDirection: "row", gap: 8 },
  chips: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  title: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  body: { fontSize: 14, color: c.onSurface },
  meta: { fontSize: 13, color: c.onSurface, lineHeight: 18 },
  swap: { fontSize: 13, fontWeight: "600", color: c.brandPrimary },
  link: { minHeight: 44, flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start" },
  linkText: { fontSize: 13, fontWeight: "700", color: c.brandPrimary },
  input: { minHeight: 48, borderRadius: 12, paddingHorizontal: 14, fontSize: 15, color: c.onSurface, backgroundColor: c.surfaceSecondary },
}));
