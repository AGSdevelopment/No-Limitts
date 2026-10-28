import { ScrollView, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/src/api";
import { Chip } from "@/src/components/ui";
import { makeStyles } from "@/src/theme";

export function placeLabel(p: any) {
  return p.address ? `${p.name}, ${p.address}` : p.name;
}

// Quick-pick from the team's AGTS favourite places.
export function PlaceChips({ selected, onPick, testID = "place-chip" }: { selected?: string; onPick: (label: string) => void; testID?: string }) {
  const styles = useStyles();
  const q = useQuery<any[]>({ queryKey: ["places"], queryFn: () => api("/places") });
  const places = [...(q.data ?? [])].sort((a, b) => b.like_count - a.like_count);
  if (!places.length) return null;
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={styles.hint}>Or pick a favourite place</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }} keyboardShouldPersistTaps="handled">
        {places.map((p) => (
          <Chip key={p.place_id} label={p.name} selected={selected === placeLabel(p)} onPress={() => onPick(placeLabel(p))} testID={`${testID}-${p.place_id}`} />
        ))}
      </ScrollView>
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  hint: { fontSize: 13, color: c.muted, marginBottom: 6 },
}));
