// Funding: Finance imports funding lines from the Excel template, sees budgets depleting and updates unit rates and support items.
// Current = still in its service period (can be rostered); History = service end date has passed. Shown as a table by participant.
import { useState } from "react";
import { Pressable, RefreshControl, ScrollView, View } from "react-native";
import * as DocumentPicker from "expo-document-picker";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders, getApiToken, openLink } from "@/src/api";
import { Text } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Sheet } from "@/src/components/participant-sheets";
import { Button, Chip, EmptyState, ErrorState, Field, Ionicons, Loading, isoToDmy } from "@/src/components/ui";
import { uploadForm } from "@/src/utils/upload";
import { makeStyles, useTheme } from "@/src/theme";

const $ = (n: number) => `$${(n ?? 0).toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

type Col = [string, (f: any) => string, number];
const COLS: Col[] = [
  ["Participant name", (f) => f.participant_name, 150], ["Participant email", (f) => f.participant_email || "-", 180],
  ["Funding management type", (f) => f.management_type, 120], ["Support item number", (f) => f.support_item_number || "-", 140],
  ["Support item name", (f) => f.support_item_name || "-", 200], ["Units", (f) => String(f.units), 70], ["Unit type", (f) => f.unit_type, 80],
  ["$ per unit", (f) => $(f.unit_rate), 90], ["Budget", (f) => $(f.budget), 100], ["Remaining", (f) => $(f.remaining), 100],
  ["Units left", (f) => String(f.units_left), 80], ["Service start date", (f) => isoToDmy(f.start_date), 100],
  ["Service end date", (f) => isoToDmy(f.end_date), 100], ["Invoice payer name", (f) => f.payer?.name || "-", 140],
  ["Invoice payer company", (f) => f.payer?.company || "-", 160], ["Invoice payer email", (f) => f.payer?.email || "-", 180],
  ["Invoice payer phone", (f) => f.payer?.phone || "-", 120], ["Invoice payer ABN", (f) => f.payer?.abn || "-", 120],
  ["Representative name", (f) => (f.payer_is_representative ? "Same as payer" : f.representative?.name || "-"), 140],
  ["Representative email", (f) => (f.payer_is_representative ? "-" : f.representative?.email || "-"), 180],
  ["Representative phone", (f) => (f.payer_is_representative ? "-" : f.representative?.phone || "-"), 120],
  ["Representative relationship", (f) => (f.payer_is_representative ? "-" : f.representative?.relationship || "-"), 130],
];

export default function Funding() {
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const acc = useQuery<any>({ queryKey: ["pm-access"], queryFn: () => api("/pm/access") });
  const q = useQuery<any[]>({ queryKey: ["funding"], queryFn: () => api("/funding"), enabled: !!(acc.data?.finance || acc.data?.rosters) });
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [open, setOpen] = useState<any>(null);
  const [rate, setRate] = useState("");
  const [mode, setMode] = useState<"keep_budget" | "increase_budget">("keep_budget");
  const [saving, setSaving] = useState(false);
  const [view, setView] = useState<"current" | "history">("current");
  const [item, setItem] = useState({ n: "", name: "" });
  const finance = !!acc.data?.finance;
  const today = new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10); // Perth date (UTC+8, no daylight saving)

  if (acc.isLoading || q.isLoading) return <Loading />;
  if (!acc.data?.finance && !acc.data?.rosters) return <EmptyState icon="lock-closed-outline" title="For Finance and Rosters users" />;
  if (q.isError) return <ErrorState message="Couldn't load funding." onRetry={q.refetch} />;
  const all = [...(q.data ?? [])].sort((a, b) => a.participant_name.localeCompare(b.participant_name) || a.start_date.localeCompare(b.start_date));
  const current = all.filter((f) => f.end_date >= today);
  const history = all.filter((f) => f.end_date < today);
  const rows = view === "current" ? current : history;

  const importFile = async () => {
    const pick = await DocumentPicker.getDocumentAsync({ copyToCacheDirectory: true,
      type: ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel"] });
    const f = pick.canceled ? null : pick.assets?.[0];
    if (!f) return;
    setImporting(true);
    try {
      const res = await uploadForm(`${API_URL}/funding/import`, { headers: authHeaders(), files: { file: { uri: f.uri, name: f.name, mimeType: f.mimeType ?? undefined } } });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Import failed");
      setResult(body);
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setImporting(false);
    }
  };
  const openRow = (f: any) => {
    setOpen(f);
    setRate("");
    setItem({ n: f.support_item_number ?? "", name: f.support_item_name ?? "" });
  };
  const saveItem = async () => {
    setSaving(true);
    try {
      const f = await api<any>(`/funding/${open.funding_id}/item`, { method: "PUT", body: { support_item_number: item.n, support_item_name: item.name } });
      setOpen(f);
      toast("Support item saved", "success");
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };
  const saveRate = async () => {
    const n = Number(rate.replace(/[$,]/g, ""));
    if (!(n > 0)) return toast("Enter the new $ per unit", "error");
    setSaving(true);
    try {
      const f = await api<any>(`/funding/${open.funding_id}/rate`, { method: "PUT", body: { unit_rate: n, mode } });
      setOpen(f);
      setRate("");
      toast("Unit rate updated", "success");
      q.refetch();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <ScrollView style={styles.root} testID="funding-screen"
        contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}>
        {finance && (
          <View style={{ gap: 8, marginBottom: 4 }}>
            <Button label="Import funding (Excel)" icon="cloud-upload-outline" loading={importing} disabled={importing} onPress={importFile} testID="funding-import" />
            <Pressable onPress={() => openLink(`${API_URL}/funding/template?token=${encodeURIComponent(getApiToken() ?? "")}`)} style={styles.link}
              accessibilityRole="button" testID="funding-template">
              <Ionicons name="download-outline" size={18} color={colors.brandPrimary} />
              <Text style={styles.linkText}>Download the funding template</Text>
            </Pressable>
            <Pressable onPress={() => openLink(`${API_URL}/funding/forecast/pdf?token=${encodeURIComponent(getApiToken() ?? "")}`)} style={styles.link}
              accessibilityRole="button" testID="funding-forecast">
              <Ionicons name="trending-down-outline" size={18} color={colors.brandPrimary} />
              <Text style={styles.linkText}>Budget forecast PDF (also emailed on the 1st)</Text>
            </Pressable>
          </View>
        )}
        <View style={styles.row}>
          <Chip label={`Current (${current.length})`} selected={view === "current"} onPress={() => setView("current")} testID="funding-current" />
          <Chip label={`History (${history.length})`} selected={view === "history"} onPress={() => setView("history")} testID="funding-history" />
        </View>
        <Text style={styles.meta}>
          {view === "current" ? "Funding still in its service period, ready to roster against." : "Funding whose service end date has passed."} Tap a row for details; scroll sideways for every column.
        </Text>
        {!rows.length ? (
          <EmptyState icon="wallet-outline" title={view === "current" ? "No current funding" : "No expired funding"}
            subtitle={view === "current" ? (finance ? "Import the funding template to add budgets." : "Finance hasn't added funding yet.") : undefined} />
        ) : (
          <ScrollView horizontal showsHorizontalScrollIndicator testID="funding-table">
            <View>
              <View style={[styles.tr, styles.th]}>
                {COLS.map(([label, , w]) => <Text key={label} style={[styles.cell, styles.thText, { width: w }]}>{label}</Text>)}
              </View>
              {rows.map((f: any, i: number) => (
                <Pressable key={f.funding_id} onPress={() => openRow(f)} style={[styles.tr, i % 2 === 1 && styles.trAlt]} testID={`funding-${f.funding_id}`}>
                  {COLS.map(([label, get, w]) => (
                    <Text key={label} numberOfLines={2}
                      style={[styles.cell, { width: w }, label === "Remaining" && (f.alert?.low || f.alert?.runout) && { color: colors.errorText, fontWeight: "700" }]}>
                      {get(f)}
                    </Text>
                  ))}
                </Pressable>
              ))}
            </View>
          </ScrollView>
        )}
      </ScrollView>

      <Sheet visible={!!result} onClose={() => setResult(null)} title="Import finished"
        sub={result ? `${result.added.length} funding line${result.added.length === 1 ? "" : "s"} added, ${result.skipped.length} skipped` : ""} testID="funding-import-result">
        {(result?.skipped ?? []).map((s: any) => (
          <Text key={s.row} style={styles.err}>Row {s.row} ({s.name}): {s.reason}</Text>
        ))}
        <Button label="Done" onPress={() => setResult(null)} />
      </Sheet>

      <Sheet visible={!!open} onClose={() => !saving && setOpen(null)} title={open?.participant_name ?? ""}
        sub={open ? `${open.management_type} · ${isoToDmy(open.start_date)} to ${isoToDmy(open.end_date)}` : ""} testID="funding-detail">
        {open && (
          <ScrollView style={{ maxHeight: 520 }} contentContainerStyle={{ gap: 10 }} keyboardShouldPersistTaps="handled">
            <Text style={styles.body}>Budget {$(open.budget)} · spent {$(open.spent)} · {$(open.remaining)} left</Text>
            <Text style={styles.meta}>{open.units} {open.unit_type} units at {$(open.unit_rate)} · {open.units_left} units left</Text>
            {open.committed > 0 && <Text style={styles.meta}>{$(open.committed)} booked in upcoming shifts</Text>}
            {open.alert?.low && <Text style={styles.err}>Low: {open.alert.pct_left}% left{open.alert.runout ? ` · runs out ~${isoToDmy(open.alert.runout)}` : ""}</Text>}
            <Text style={styles.label}>Support item</Text>
            <Text style={styles.body}>{[open.support_item_number, open.support_item_name].filter(Boolean).join(" · ") || "Not set"}</Text>
            {finance && (
              <>
                <Field label="Support item number" value={item.n} onChangeText={(v) => setItem({ ...item, n: v })} placeholder="01_011_0107_1_1" testID="funding-item-number" />
                <Field label="Support item name" value={item.name} onChangeText={(v) => setItem({ ...item, name: v })} testID="funding-item-name" />
                <Button label="Save support item" icon="pricetag-outline" variant="secondary" loading={saving} disabled={saving} onPress={saveItem} testID="funding-item-save" />
              </>
            )}
            <Text style={styles.label}>Invoice payer</Text>
            <Text style={styles.body}>{[open.payer.company, open.payer.name].filter(Boolean).join(" · ")}</Text>
            <Text style={styles.meta}>{open.payer.email} · {open.payer.phone}{open.payer.abn ? ` · ABN ${open.payer.abn}` : ""}</Text>
            <Text style={styles.label}>Participant&apos;s representative</Text>
            <Text style={styles.body}>{open.payer_is_representative ? "Same as invoice payer" : `${open.representative.name}${open.representative.relationship ? ` (${open.representative.relationship})` : ""}`}</Text>
            {!open.payer_is_representative && <Text style={styles.meta}>{open.representative.email} · {open.representative.phone}</Text>}
            {!!open.rate_history?.length && (
              <>
                <Text style={styles.label}>Rate changes</Text>
                {open.rate_history.map((h: any, i: number) => (
                  <Text key={i} style={styles.meta}>{isoToDmy(h.effective)}: {$(h.from_rate)} → {$(h.to_rate)} ({h.mode === "keep_budget" ? "budget kept" : `budget ${$(h.from_budget)} → ${$(h.to_budget)}`}) by {h.by}</Text>
                ))}
              </>
            )}
            {finance && open.end_date >= today && (
              <>
                <Text style={styles.label}>Update unit rate (NDIS / Aged Care price change)</Text>
                <Field label="New $ per unit" value={rate} onChangeText={setRate} keyboardType="decimal-pad" placeholder={String(open.unit_rate)} testID="funding-rate-input" />
                <View style={styles.row}>
                  <Chip label="Keep total budget" selected={mode === "keep_budget"} onPress={() => setMode("keep_budget")} testID="funding-rate-keep" />
                  <Chip label="Increase budget" selected={mode === "increase_budget"} onPress={() => setMode("increase_budget")} testID="funding-rate-increase" />
                </View>
                <Text style={styles.meta}>
                  {mode === "keep_budget" ? "The budget stays the same, so fewer units are left at the new rate."
                    : "The units left stay the same, and the budget grows by the rate change for the rest of the service period."}
                </Text>
                <Button label="Save new rate" icon="pricetag-outline" loading={saving} disabled={saving} onPress={saveRate} testID="funding-rate-save" />
              </>
            )}
            <Button label="Close" variant="ghost" onPress={() => setOpen(null)} />
          </ScrollView>
        )}
      </Sheet>
    </>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  row: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  body: { fontSize: 14, color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
  label: { fontSize: 12, fontWeight: "700", color: c.muted, textTransform: "uppercase", marginTop: 4 },
  link: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, alignSelf: "center" },
  linkText: { fontSize: 14, fontWeight: "700", color: c.brandPrimary },
  err: { fontSize: 13, color: c.errorText, lineHeight: 18 },
  tr: { flexDirection: "row", backgroundColor: c.surface, borderBottomWidth: 1, borderColor: c.surfaceSecondary, minHeight: 48, alignItems: "center" },
  trAlt: { backgroundColor: c.background },
  th: { backgroundColor: c.brandTertiary },
  thText: { fontWeight: "800", color: c.onSurface, fontSize: 12 },
  cell: { paddingHorizontal: 8, paddingVertical: 6, fontSize: 13, color: c.onSurface },
}));
