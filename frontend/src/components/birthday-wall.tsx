// Birthday card wall: assigned Support Workers and Coordinators sign a participant's birthday card (open 7 days either side).
import { useState } from "react";
import { Pressable, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { API_URL, api, getApiToken, openLink } from "@/src/api";
import { Text, TextInput } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Avatar, Button, Ionicons } from "@/src/components/ui";
import { Sheet } from "@/src/components/participant-sheets";
import { makeStyles, useTheme } from "@/src/theme";

export function BirthdayWall({ participantId, name, canEmail, contacts }: {
  participantId: string; name: string; canEmail?: boolean; contacts?: { name: string; relationship?: string; email?: string }[];
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const q = useQuery<any>({ queryKey: ["birthday-wall", participantId], queryFn: () => api(`/participants/${participantId}/birthday-wall`) });
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const [sending, setSending] = useState<string | null>(null);
  const family = (contacts ?? []).filter((c) => !!c.email?.trim());
  if (!q.data?.open) return null;
  const { birthday, messages } = q.data;
  const mine = messages.find((m: any) => m.mine);
  const first = name.split(" ")[0];

  const emailTo = async (c: { name: string; email?: string }) => {
    setSending(c.email ?? "");
    try {
      await api(`/participants/${participantId}/birthday-wall/email`, { method: "POST", body: { email: c.email } });
      toast(`Birthday card emailed to ${c.name}`, "success");
      setEmailOpen(false);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSending(null);
    }
  };

  const sign = async () => {
    setBusy(true);
    try {
      await api(`/participants/${participantId}/birthday-wall`, { method: "POST", body: { text: text ?? "" } });
      setText(null);
      toast(mine ? "Message updated" : "You signed the card 🎉", "success");
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const remove = async (id: string) => {
    try {
      await api(`/participants/${participantId}/birthday-wall/${id}`, { method: "DELETE" });
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const when = birthday.in_days === 0 ? "today" : birthday.in_days > 0
    ? (birthday.in_days === 1 ? "tomorrow" : `in ${birthday.in_days} days`)
    : `${-birthday.in_days} day${birthday.in_days === -1 ? "" : "s"} ago`;

  return (
    <View style={styles.card} testID="birthday-wall">
      <Text style={styles.title}>🎂 {first}&apos;s birthday card</Text>
      <Text style={styles.meta}>{first} {birthday.in_days < 0 ? "turned" : "turns"} {birthday.turns} {when}. Sign the card for the team to share with them.</Text>
      {messages.map((m: any) => (
        <View key={m.message_id} style={styles.msg} testID={`birthday-msg-${m.message_id}`}>
          <Avatar name={m.name} size={32} />
          <View style={{ flex: 1 }}>
            <Text style={styles.body}>{m.text}</Text>
            <Text style={styles.from}>{m.name}</Text>
          </View>
          {m.can_remove && (
            <Pressable onPress={() => remove(m.message_id)} hitSlop={10} style={styles.iconBtn} accessibilityLabel={`Remove message from ${m.name}`}
              testID={`birthday-msg-remove-${m.message_id}`}>
              <Ionicons name="trash-outline" size={16} color={colors.muted} />
            </Pressable>
          )}
        </View>
      ))}
      {!messages.length && <Text style={styles.meta}>No messages yet. Be the first to sign!</Text>}
      {!!messages.length && (
        <Button label="Print card (PDF)" icon="print-outline" variant="secondary"
          onPress={() => openLink(`${API_URL}/participants/${participantId}/birthday-wall/pdf?token=${encodeURIComponent(getApiToken() ?? "")}`)}
          testID="birthday-wall-print" />
      )}
      {!!messages.length && canEmail && (
        <Button label="Email card to family" icon="mail-outline" variant="secondary" onPress={() => setEmailOpen(true)} testID="birthday-wall-email" />
      )}
      <Sheet visible={emailOpen} onClose={() => !sending && setEmailOpen(false)} title={`Email ${first}'s card`}
        sub="They'll get a private link to the printable card, valid for 30 days." testID="birthday-email-sheet">
        {family.length ? family.map((c) => (
          <Pressable key={c.email} onPress={() => emailTo(c)} disabled={!!sending} style={styles.contact}
            accessibilityRole="button" testID={`birthday-email-to-${c.email}`}>
            <Avatar name={c.name} size={36} />
            <View style={{ flex: 1 }}>
              <Text style={styles.body}>{c.name}{c.relationship ? ` · ${c.relationship}` : ""}</Text>
              <Text style={styles.meta}>{c.email}</Text>
            </View>
            <Ionicons name={sending === c.email ? "hourglass-outline" : "send-outline"} size={18} color={colors.brandPrimary} />
          </Pressable>
        )) : (
          <Text style={styles.meta} testID="birthday-email-no-contacts">
            No key contacts with an email address yet. Add one in the profile&apos;s Key contacts first.
          </Text>
        )}
        <Button label="Cancel" variant="ghost" disabled={!!sending} onPress={() => setEmailOpen(false)} />
      </Sheet>
      {text === null ? (
        <Button label={mine ? "Edit my message" : "Sign the card"} icon="create-outline" variant="secondary"
          onPress={() => setText(mine?.text ?? "")} testID="birthday-wall-sign" />
      ) : (
        <>
          <TextInput value={text} onChangeText={setText} placeholder={`Happy birthday ${first}! …`} placeholderTextColor={colors.muted}
            maxLength={300} multiline style={styles.input} autoFocus testID="birthday-wall-input" />
          <View style={styles.row}>
            <Button label="Post" icon="heart-outline" loading={busy} disabled={busy || !text.trim()} onPress={sign} style={{ flex: 1 }}
              testID="birthday-wall-post" />
            <Button label="Cancel" variant="ghost" onPress={() => setText(null)} style={{ flex: 1 }} />
          </View>
        </>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  card: { backgroundColor: c.surface, borderRadius: 14, padding: 14, gap: 10, borderWidth: 2, borderColor: c.brandPrimary },
  title: { fontSize: 17, fontWeight: "800", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
  msg: { flexDirection: "row", alignItems: "flex-start", gap: 10, backgroundColor: c.brandTertiary, borderRadius: 12, padding: 10 },
  body: { fontSize: 14, color: c.onSurface, lineHeight: 20 },
  from: { fontSize: 12, fontWeight: "700", color: c.brandPrimary, marginTop: 2 },
  iconBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  contact: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 56, paddingVertical: 6 },
  row: { flexDirection: "row", gap: 8 },
  input: { minHeight: 80, borderRadius: 12, padding: 12, fontSize: 15, color: c.onSurface, backgroundColor: c.surfaceSecondary, textAlignVertical: "top" },
}));
