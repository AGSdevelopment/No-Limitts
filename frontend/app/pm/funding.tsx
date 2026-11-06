// Funding: Finance imports funding lines from the Excel template, sees budgets depleting and updates unit rates.
import { useState } from "react";
import { FlatList, Pressable, RefreshControl, ScrollView, View } from "react-native";
import * as DocumentPicker from "expo-document-picker";
import { useQuery } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, authHeaders, getApiToken, openLink } from "@/src/api";
import { Text } from "@/src/components/text";
import { useToast } from "@/src/components/toast";
import { Sheet } from "@/src/components/participant-sheets";
import { Button, Chip, EmptyState, ErrorState, Field, Ionicons, Loading, Pill, isoToDmy } from "@/src/components/ui";
import { uploadForm } from "@/src/utils/upload";
import { makeStyles, useTheme } from "@/src/theme";

const $ = (n: number) => `$${(n ?? 0).toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

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
  const finance = !!acc.data?.finance;

  if (acc.isLoading || q.isLoading) return <Loading />;
  if (!acc.data?.finance && !acc.data?.rosters) return <EmptyState icon="lock-closed-outline" title="For Finance and Rosters users" />;
  if (q.isError) return <ErrorState message="Couldn't load funding." onRetry={q.refetch} />;

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
      <FlatList
        style={styles.root}
        testID="funding-screen"
        data={q.data ?? []}
        keyExtractor={(f) => f.funding_id}
        contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: insets.bottom + 24, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.brandPrimary} />}
        ListHeaderComponent={finance ? (
          <View style={{ gap: 8, marginBottom: 4 }}>
            <Button label="Import funding (Excel)" icon="cloud-upload-outline" loading={importing} disabled={importing} onPress={importFile} testID="funding-import" />
            <Pressable onPress={() => openLink(`${API_URL}/funding/template?token=${encodeURIComponent(getApiToken() ?? "")}`)} style={styles.link}
              accessibilityRole="button" testID="funding-template">
              <Ionicons name="download-outline" size={18} color={colors.brandPrimary} />
              <Text style={styles.linkText}>Download the funding template</Text>
            </Pressable>
          </View>
        ) : null}
        ListEmptyComponent={<EmptyState icon="wallet-outline" title="No funding yet" subtitle={finance ? "Import the funding template to add budgets." : "Finance hasn't added funding yet."} />}
        renderItem={({ item: f }) => {
          const pct = f.budget ? Math.max(0, Math.min(1, f.remaining / f.budget)) : 0;
          return (
            <Pressable onPress={() => { setOpen(f); setRate(""); }} style={styles.card} testID={`funding-${f.funding_id}`}>
              <View style={styles.row}>
                <Text style={[styles.title, { flex: 1 }]}>{f.participant_name}</Text>
                <Pill label={f.management_type} tone="accent" />
              </View>
              <Text style={styles.meta}>{isoToDmy(f.start_date)} to {isoToDmy(f.end_date)} · {f.unit_type} @ {$(f.unit_rate)}{f.active ? "" : " · not active"}</Text>
              <View style={styles.bar}><View style={[styles.fill, { width: `${pct * 100}%` }]} /></View>
              <Text style={styles.body}>{$(f.remaining)} left of {$(f.budget)} · {f.units_left} of {f.units} units</Text>
              {f.committed > 0 && <Text style={styles.meta}>{$(f.committed)} booked in upcoming shifts</Text>}
              {(f.alert?.low || f.alert?.runout) && (
                <View style={styles.row} testID={`funding-alert-${f.funding_id}`}>
                  {f.alert.low && <Pill label={`Low: ${f.alert.pct_left}% left`} tone="accent" />}
                  {!!f.alert.runout && <Pill label={`Runs out ~${isoToDmy(f.alert.runout)}`} tone="accent" />}
                </View>
              )}
            </Pressable>
          );
        }}
      />

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
            {finance && (
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
  card: { backgroundColor: c.surface, borderRadius: 14, padding: 14, gap: 6 },
  row: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  title: { fontSize: 16, fontWeight: "700", color: c.onSurface },
  body: { fontSize: 14, color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
  label: { fontSize: 12, fontWeight: "700", color: c.muted, textTransform: "uppercase", marginTop: 4 },
  bar: { height: 8, borderRadius: 4, backgroundColor: c.surfaceSecondary, overflow: "hidden" },
  fill: { height: 8, backgroundColor: c.brandPrimary },
  link: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, alignSelf: "center" },
  linkText: { fontSize: 14, fontWeight: "700", color: c.brandPrimary },
  err: { fontSize: 13, color: c.errorText, lineHeight: 18 },
}));
