// Participant invoices (Finance): create GST-free invoices from completed shifts, one per funding payer; download PDFs, mark paid or void.
import { useState } from "react";
import { FlatList, Pressable, RefreshControl, ScrollView, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, getApiToken, openLink } from "@/src/api";
import { Text } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { ConfirmSheet, Sheet } from "@/src/components/participant-sheets";
import { Button, Chip, EmptyState, ErrorState, Field, Ionicons, Loading, Pill, dmyToIso, isoToDmy } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const $ = (n: number) => `$${(n ?? 0).toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const FILTERS = [["", "All"], ["unpaid", "Unpaid"], ["paid", "Paid"], ["void", "Void"]];
const FIELDS: [string, string][] = [["business_name", "Business name"], ["abn", "ABN"], ["address", "Address"], ["email", "Email"], ["phone", "Phone"],
  ["account_name", "Bank account name"], ["bsb", "BSB"], ["account_number", "Account number"]];

export default function Invoices() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const [filter, setFilter] = useState("");
  const q = useQuery<any[]>({ queryKey: ["invoices", filter], queryFn: () => api(`/invoices${filter ? `?status=${filter}` : ""}`) });
  const [range, setRange] = useState({ from: "", to: "" });
  const [preview, setPreview] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState<any>(null);
  const [voiding, setVoiding] = useState<any>(null);

  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as any)?.message ?? "Couldn't load invoices."} onRetry={q.refetch} />;

  const check = async () => {
    const a = dmyToIso(range.from), b = dmyToIso(range.to);
    if (!a || !b) return toast("Enter both dates as DD-MM-YYYY", "error");
    if (a > b) return toast("The start date must be before the end date", "error");
    try {
      setPreview({ ...(await api<any>(`/invoices/uninvoiced?date_from=${range.from.trim()}&date_to=${range.to.trim()}`)), from: range.from.trim(), to: range.to.trim() });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const generate = async () => {
    setBusy(true);
    try {
      const r = await api<any>("/invoices/generate", { method: "POST", body: { date_from: preview.from, date_to: preview.to } });
      toast(r.count ? `${r.count} invoice${r.count === 1 ? "" : "s"} created` : "No completed shifts left to invoice in that period", r.count ? "success" : "info");
      setPreview(null);
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const setStatus = async (inv: any, status: string) => {
    setBusy(true);
    try {
      await api(`/invoices/${inv.invoice_id}/status`, { method: "POST", body: { status } });
      toast(status === "paid" ? "Marked as paid" : status === "void" ? "Invoice voided. Its shifts can be invoiced again." : "Marked as unpaid", "success");
      setVoiding(null);
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const openSettings = async () => {
    try {
      setSettings(await api("/invoices/settings"));
    } catch (e: any) {
      toast(e.message, "error");
    }
  };
  const saveSettings = async () => {
    setBusy(true);
    try {
      await api("/invoices/settings", { method: "PUT", body: { ...settings, payment_terms_days: Number(settings.payment_terms_days) || 0 } });
      toast("Invoice details saved", "success");
      setSettings(null);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <FlatList
        style={styles.root}
        testID="invoices-screen"
        data={q.data ?? []}
        keyExtractor={(i) => i.invoice_id}
        contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}
        ListHeaderComponent={
          <View style={{ gap: 10, marginBottom: 4 }}>
            <Text style={styles.section}>Create invoices</Text>
            <Text style={styles.meta}>One GST-free invoice per funding payer, from completed shifts at their approved times. Shifts are only invoiced once.</Text>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <View style={{ flex: 1 }}><Field label="From" value={range.from} onChangeText={(v) => setRange({ ...range, from: v })} placeholder="DD-MM-YYYY" testID="inv-from" /></View>
              <View style={{ flex: 1 }}><Field label="To" value={range.to} onChangeText={(v) => setRange({ ...range, to: v })} placeholder="DD-MM-YYYY" testID="inv-to" /></View>
            </View>
            <Button label="Check what's ready to invoice" icon="receipt-outline" onPress={check} testID="inv-check" />
            <Pressable onPress={openSettings} style={styles.link} accessibilityRole="button" testID="inv-settings">
              <Ionicons name="business-outline" size={18} color={colors.brandPrimary} />
              <Text style={styles.linkText}>Business and bank details on invoices</Text>
            </Pressable>
            <View style={styles.chips}>
              {FILTERS.map(([k, label]) => <Chip key={k} label={label} selected={filter === k} onPress={() => setFilter(k)} testID={`inv-filter-${k || "all"}`} />)}
            </View>
          </View>
        }
        ListEmptyComponent={<EmptyState icon="receipt-outline" title="No invoices yet" subtitle="Choose a period above to create invoices from completed shifts." />}
        renderItem={({ item: i }) => (
          <View style={styles.card} testID={`invoice-${i.invoice_id}`}>
            <View style={styles.row}>
              <Text style={[styles.title, { flex: 1 }]}>{i.number} · {i.participant_name}</Text>
              <Pill label={i.status === "paid" ? "Paid" : i.status === "void" ? "Void" : "Unpaid"} tone={i.status === "paid" ? "brand" : i.status === "void" ? "muted" : "accent"} />
            </View>
            <Text style={styles.body}>{$(i.total)} · {i.shifts} shift{i.shifts === 1 ? "" : "s"} · {i.management_type}</Text>
            <Text style={styles.meta}>To {[i.payer?.company, i.payer?.name].filter(Boolean).join(" · ")} · {isoToDmy(i.period_from)} to {isoToDmy(i.period_to)} · due {isoToDmy(i.due_date)}</Text>
            <View style={styles.row}>
              <Button label="PDF" icon="document-text-outline" variant="secondary" style={{ flex: 1 }} testID={`inv-pdf-${i.invoice_id}`}
                onPress={() => openLink(`${API_URL}/invoices/${i.invoice_id}/pdf?token=${encodeURIComponent(getApiToken() ?? "")}`)} />
              {i.status !== "void" && (
                <Button label={i.status === "paid" ? "Mark unpaid" : "Mark paid"} icon={i.status === "paid" ? "arrow-undo-outline" : "checkmark"} style={{ flex: 1 }}
                  disabled={busy} onPress={() => setStatus(i, i.status === "paid" ? "unpaid" : "paid")} testID={`inv-paid-${i.invoice_id}`} />
              )}
            </View>
            {i.status === "unpaid" && (
              <Pressable onPress={() => setVoiding(i)} style={styles.link} testID={`inv-void-${i.invoice_id}`}>
                <Ionicons name="close-circle-outline" size={16} color={colors.errorText} />
                <Text style={[styles.meta, { color: colors.errorText, fontWeight: "700" }]}>Void invoice</Text>
              </Pressable>
            )}
          </View>
        )}
      />

      <Sheet visible={!!preview} onClose={() => !busy && setPreview(null)} title="Ready to invoice" sub={preview ? `${preview.from} to ${preview.to}` : ""} testID="inv-preview">
        {preview && (
          <>
            <Text style={styles.body}>{preview.shifts} completed shift{preview.shifts === 1 ? "" : "s"} not yet invoiced · {$(preview.total)}</Text>
            <Text style={styles.meta}>{preview.invoices} invoice{preview.invoices === 1 ? "" : "s"} will be created (one per funding payer). No GST.</Text>
            {preview.pending > 0 && (
              <Text style={[styles.meta, { color: colors.warningText, fontWeight: "700" }]} testID="inv-preview-pending">
                {preview.pending} shift{preview.pending === 1 ? " is" : "s are"} still awaiting clock-time approval and won&apos;t be included. Run this period again once approved.
              </Text>
            )}
            <Button label="Create invoices" icon="add" loading={busy} disabled={busy || !preview.shifts} onPress={generate} testID="inv-generate" />
          </>
        )}
        <Button label="Cancel" variant="ghost" onPress={() => setPreview(null)} />
      </Sheet>

      <Sheet visible={!!settings} onClose={() => !busy && setSettings(null)} title="Invoice details" sub="Shown on new invoices. Existing invoices keep the details they were made with." testID="inv-settings-sheet">
        {settings && (
          <ScrollView style={{ maxHeight: 480 }} contentContainerStyle={{ gap: 8 }} keyboardShouldPersistTaps="handled">
            {FIELDS.map(([k, label]) => (
              <Field key={k} label={label} value={settings[k] ?? ""} onChangeText={(v) => setSettings({ ...settings, [k]: v })} testID={`inv-set-${k}`} />
            ))}
            <Field label="Payment terms (days)" value={String(settings.payment_terms_days ?? "")} keyboardType="number-pad"
              onChangeText={(v) => setSettings({ ...settings, payment_terms_days: v.replace(/\D/g, "") })} testID="inv-set-terms" />
            <Button label="Save details" icon="checkmark" loading={busy} disabled={busy} onPress={saveSettings} testID="inv-set-save" />
            <Button label="Cancel" variant="ghost" onPress={() => setSettings(null)} />
          </ScrollView>
        )}
      </Sheet>

      <ConfirmSheet visible={!!voiding} title={`Void ${voiding?.number ?? ""}?`} sub="The invoice stays on record as void and its shifts can be invoiced again."
        confirmLabel="Void invoice" busy={busy} onConfirm={() => setStatus(voiding, "void")} onClose={() => setVoiding(null)} />
    </>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  card: { backgroundColor: c.surface, borderRadius: 14, padding: 14, gap: 6 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  chips: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  section: { fontSize: 13, fontWeight: "700", color: c.muted, textTransform: "uppercase" },
  title: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  body: { fontSize: 14, color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
  link: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, alignSelf: "flex-start" },
  linkText: { fontSize: 14, fontWeight: "700", color: c.brandPrimary },
}));
