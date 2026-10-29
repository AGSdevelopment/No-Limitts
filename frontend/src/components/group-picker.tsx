import { Modal, Pressable, ScrollView, View } from "react-native";
import { Text } from "@/src/components/text";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Button, Ionicons } from "@/src/components/ui";
import { STAFF_GROUPS } from "@/src/groups";
import { makeStyles, useTheme } from "@/src/theme";

type Props = {
  visible: boolean;
  title: string;
  subtitle?: string;
  multi: boolean;
  selected: string[];
  onChange: (next: string[]) => void;
  onClose: () => void;
  onSave?: () => void;
  saving?: boolean;
  emptyLabel: string; // "Everyone" (forms) or "No group" (people)
  emptyHint?: string;
};

// Bottom sheet for picking staff groups: multi-select for form access, single-select for a person's group.
export function GroupPickerSheet({ visible, title, subtitle, multi, selected, onChange, onClose, onSave, saving, emptyLabel, emptyHint }: Props) {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();

  const toggle = (key: string) => {
    if (!multi) return onChange([key]);
    onChange(selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key]);
  };

  const Row = ({ label, on, onPress, testID, hint }: { label: string; on: boolean; onPress: () => void; testID: string; hint?: string }) => (
    <Pressable testID={testID} onPress={onPress} style={({ pressed }) => [styles.row, pressed && { opacity: 0.7 }]}>
      <Ionicons
        name={multi ? (on ? "checkbox" : "square-outline") : on ? "radio-button-on" : "radio-button-off"}
        size={22}
        color={on ? colors.brandPrimary : colors.borderStrong}
      />
      <View style={{ flex: 1 }}>
        <Text style={styles.rowLabel}>{label}</Text>
        {hint && <Text style={styles.rowHint}>{hint}</Text>}
      </View>
    </Pressable>
  );

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.scrim} onPress={onClose} testID="group-picker-backdrop" />
      <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID="group-picker-sheet">
        <View style={styles.grabber} />
        <Text style={styles.title}>{title}</Text>
        {subtitle && <Text style={styles.subtitle}>{subtitle}</Text>}
        <ScrollView style={{ maxHeight: 380 }}>
          <Row label={emptyLabel} hint={emptyHint} on={selected.length === 0} onPress={() => onChange([])} testID="group-picker-none" />
          {STAFF_GROUPS.map((g) => (
            <Row key={g.key} label={g.label} on={selected.includes(g.key)} onPress={() => toggle(g.key)} testID={`group-picker-${g.key}`} />
          ))}
        </ScrollView>
        {onSave && <Button label="Save" loading={saving} onPress={onSave} style={{ marginTop: 16 }} testID="group-picker-save" />}
        <Button label="Cancel" variant="ghost" onPress={onClose} style={{ marginTop: 4 }} testID="group-picker-cancel" />
      </View>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  scrim: { flex: 1, backgroundColor: c.scrim },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 24, paddingTop: 12 },
  grabber: { width: 36, height: 5, borderRadius: 3, backgroundColor: c.borderStrong, alignSelf: "center", marginBottom: 16 },
  title: { fontSize: 20, fontWeight: "700", color: c.onSurface },
  subtitle: { fontSize: 14, color: c.muted, marginTop: 4, marginBottom: 8, lineHeight: 20 },
  row: { flexDirection: "row", alignItems: "center", gap: 12, minHeight: 52, borderBottomWidth: 0.5, borderBottomColor: c.divider },
  rowLabel: { fontSize: 16, color: c.onSurface },
  rowHint: { fontSize: 12, color: c.muted },
}));
