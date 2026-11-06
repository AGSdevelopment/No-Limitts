// Rosters: week-at-a-glance grid of every worker's shifts (rows = workers, columns = Mon–Sun).
import { useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/src/api";
import { Text } from "@/src/components/text";
import { Chip, Ionicons, Loading } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function monday(d: Date) {
  const m = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  m.setDate(m.getDate() - ((m.getDay() + 6) % 7));
  return m;
}

export function WeekRoster({ onOpen }: { onOpen: (shiftId: string) => void }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [start, setStart] = useState(() => monday(new Date()));
  const [mode, setMode] = useState<"worker" | "participant">("worker");
  const [pid, setPid] = useState("");
  const days = Array.from({ length: 7 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  const from = iso(days[0]), to = iso(days[6]);
  const q = useQuery<any[]>({ queryKey: ["week-roster", from], queryFn: () => api(`/shifts?date_from=${from}&date_to=${to}`) });
  const people = useQuery<any[]>({ queryKey: ["pm-participants"], queryFn: () => api("/pm/participants"), enabled: mode === "participant" });
  const shifts = (q.data ?? []).filter((s) => !["cancelled", "declined"].includes(s.status)).filter((s) => mode === "worker" || !pid || s.participant_id === pid);
  const byP = mode === "participant";
  const rowsOf = (s: any) => (byP ? [s.participant_id, s.participant_name] : [s.worker_id, s.worker_name]);
  const pidName = (people.data ?? []).find((p) => p.participant_id === pid)?.name;
  const rows: [string, string][] = [...new Map(shifts.map((s) => rowsOf(s) as [string, string])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  if (byP && pid && !rows.length && pidName) rows.push([pid, pidName]);
  const workers = rows;
  const shift = (n: number) => setStart(new Date(start.getFullYear(), start.getMonth(), start.getDate() + n * 7));
  const tone = (st: string) => (st === "pending_acceptance" ? colors.warningSoft : st === "awaiting_approval" ? colors.errorSoft : st === "completed" ? colors.successSoft : colors.brandTertiary);

  return (
    <View style={{ gap: 10 }} testID="week-roster">
      <View style={styles.nav}>
        <Pressable onPress={() => shift(-1)} style={styles.navBtn} accessibilityLabel="Previous week" testID="week-prev">
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title} testID="week-label">{pad(days[0].getDate())}-{pad(days[0].getMonth() + 1)} to {pad(days[6].getDate())}-{pad(days[6].getMonth() + 1)}-{days[6].getFullYear()}</Text>
        <Pressable onPress={() => shift(1)} style={styles.navBtn} accessibilityLabel="Next week" testID="week-next">
          <Ionicons name="chevron-forward" size={22} color={colors.onSurface} />
        </Pressable>
      </View>
      <View style={styles.chips}>
        <Chip label="By worker" selected={!byP} onPress={() => setMode("worker")} testID="week-mode-worker" />
        <Chip label="By participant" selected={byP} onPress={() => setMode("participant")} testID="week-mode-participant" />
      </View>
      {byP && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
          <Chip label="All participants" selected={!pid} onPress={() => setPid("")} testID="week-p-all" />
          {(people.data ?? []).map((p) => (
            <Chip key={p.participant_id} label={p.name} selected={pid === p.participant_id} onPress={() => setPid(p.participant_id)} testID={`week-p-${p.participant_id}`} />
          ))}
        </ScrollView>
      )}
      <Text style={styles.meta}>{shifts.length} shift{shifts.length === 1 ? "" : "s"} · {workers.length} {byP ? "participant" : "worker"}{workers.length === 1 ? "" : "s"} · amber = needs acceptance, red = times to approve, green = done</Text>
      {q.isLoading ? <Loading /> : !workers.length ? <Text style={styles.meta}>No shifts rostered this week.</Text> : (
        <ScrollView horizontal showsHorizontalScrollIndicator>
          <View>
            <View style={styles.row}>
              <View style={[styles.nameCell, styles.head]}><Text style={styles.headText}>{byP ? "Participant" : "Worker"}</Text></View>
              {days.map((d, i) => (
                <View key={i} style={[styles.dayCell, styles.head]}>
                  <Text style={styles.headText}>{DAYS[i]} {pad(d.getDate())}</Text>
                </View>
              ))}
            </View>
            {workers.map(([wid, name]) => (
              <View key={wid} style={styles.row} testID={`week-row-${wid}`}>
                <View style={styles.nameCell}><Text style={styles.name} numberOfLines={2}>{name}</Text></View>
                {days.map((d, i) => (
                  <View key={i} style={styles.dayCell}>
                    {shifts.filter((s) => rowsOf(s)[0] === wid && s.date === iso(d)).map((s) => (
                      <Pressable key={s.shift_id} onPress={() => onOpen(s.shift_id)} style={[styles.chip, { backgroundColor: tone(s.status) }]}
                        testID={`week-shift-${s.shift_id}`}>
                        <Text style={styles.chipTime}>{s.start}–{s.end}</Text>
                        <Text style={styles.chipName} numberOfLines={1}>{byP ? s.worker_name : s.participant_name}</Text>
                      </Pressable>
                    ))}
                  </View>
                ))}
              </View>
            ))}
          </View>
        </ScrollView>
      )}
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  nav: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  chips: { flexDirection: "row", gap: 8, flexWrap: "nowrap" },
  navBtn: { width: 48, height: 48, alignItems: "center", justifyContent: "center", borderRadius: 24, backgroundColor: c.surface },
  title: { fontSize: 16, fontWeight: "800", color: c.onSurface },
  meta: { fontSize: 13, color: c.muted, lineHeight: 18 },
  row: { flexDirection: "row" },
  head: { backgroundColor: c.surfaceSecondary, minHeight: 36, justifyContent: "center" },
  headText: { fontSize: 12, fontWeight: "700", color: c.muted },
  nameCell: { width: 96, padding: 6, borderBottomWidth: 1, borderColor: c.surfaceSecondary, backgroundColor: c.surface, justifyContent: "center" },
  name: { fontSize: 13, fontWeight: "700", color: c.onSurface },
  dayCell: { width: 104, padding: 4, gap: 4, borderBottomWidth: 1, borderLeftWidth: 1, borderColor: c.surfaceSecondary, backgroundColor: c.surface, minHeight: 56 },
  chip: { borderRadius: 8, padding: 4 },
  chipTime: { fontSize: 11, fontWeight: "800", color: c.onSurface },
  chipName: { fontSize: 11, color: c.onSurface },
}));
