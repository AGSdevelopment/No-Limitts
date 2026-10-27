import React from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  PressableProps,
  StyleProp,
  Text,
  TextInput,
  TextInputProps,
  View,
  ViewStyle,
} from "react-native";
import { Image } from "expo-image";
import * as Haptics from "expo-haptics";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons, IoniconsIconName } from "@react-native-vector-icons/ionicons";

import { makeStyles, useTheme } from "@/src/theme";

export { Ionicons };
export type IconName = IoniconsIconName;

export function tap() {
  Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
}

export function formatDate(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function timeAgo(iso?: string) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d`;
  return formatDate(iso);
}

export function isoDate(d: Date) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

// Dates are typed and shown as dd-mm-yyyy; the API stores yyyy-mm-dd.
export function dmyDate(d: Date) {
  return isoToDmy(isoDate(d));
}

export function isoToDmy(iso?: string) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  return m ? `${m[3]}-${m[2]}-${m[1]}` : iso ?? "";
}

export function dmyToIso(s: string): string | null {
  const m = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/.exec(s.trim());
  if (!m) return null;
  const [d, mo, y] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const dt = new Date(y, mo - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null;
  return isoDate(dt);
}

type BtnProps = PressableProps & {
  label: string;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  icon?: IconName;
  loading?: boolean;
  style?: StyleProp<ViewStyle>;
};

export function Button({ label, variant = "primary", icon, loading, disabled, style, onPress, ...rest }: BtnProps) {
  const styles = useStyles();
  const { colors } = useTheme();
  const fg =
    variant === "primary" ? colors.onBrandPrimary : variant === "danger" ? colors.onError : colors.onBrandSecondary;
  return (
    <Pressable
      {...rest}
      disabled={disabled || loading}
      onPress={(e) => {
        tap();
        onPress?.(e);
      }}
      style={({ pressed }) => [
        styles.btn,
        variant === "primary" && { backgroundColor: colors.brandPrimary },
        variant === "secondary" && { backgroundColor: colors.brandSecondary },
        variant === "ghost" && { backgroundColor: "transparent" },
        variant === "danger" && { backgroundColor: colors.error },
        (disabled || loading) && { opacity: 0.5 },
        pressed && { opacity: 0.8, transform: [{ scale: 0.98 }] },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <>
          {icon && <Ionicons name={icon} size={18} color={fg} />}
          <Text style={[styles.btnText, { color: fg }]}>{label}</Text>
        </>
      )}
    </Pressable>
  );
}

export function Card({ children, style, onPress, testID }: { children: React.ReactNode; style?: StyleProp<ViewStyle>; onPress?: () => void; testID?: string }) {
  const styles = useStyles();
  if (onPress) {
    return (
      <Pressable testID={testID} onPress={onPress} style={({ pressed }) => [styles.card, pressed && { opacity: 0.85 }, style]}>
        {children}
      </Pressable>
    );
  }
  return (
    <View testID={testID} style={[styles.card, style]}>
      {children}
    </View>
  );
}

export function StatusBadge({ status, testID }: { status: "valid" | "expiring" | "expired"; testID?: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const map = {
    valid: { bg: colors.successSoft, fg: colors.successText, label: "Valid" },
    expiring: { bg: colors.warningSoft, fg: colors.warningText, label: "Expiring" },
    expired: { bg: colors.errorSoft, fg: colors.errorText, label: "Expired" },
  }[status];
  return (
    <View testID={testID} style={[styles.badge, { backgroundColor: map.bg }]}>
      <Text style={[styles.badgeText, { color: map.fg }]}>{map.label}</Text>
    </View>
  );
}

export function Pill({ label, tone = "brand" }: { label: string; tone?: "brand" | "muted" | "accent" }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const bg = tone === "brand" ? colors.brandSecondary : tone === "accent" ? colors.accentSoft : colors.surfaceSecondary;
  const fg = tone === "brand" ? colors.onBrandSecondary : tone === "accent" ? colors.accent : colors.onSurfaceSecondary;
  return (
    <View style={[styles.badge, { backgroundColor: bg }]}>
      <Text style={[styles.badgeText, { color: fg }]}>{label}</Text>
    </View>
  );
}

export function Avatar({ name, picture, size = 40 }: { name?: string; picture?: string | null; size?: number }) {
  const styles = useStyles();
  const initials = (name || "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  if (picture) {
    return <Image source={{ uri: picture }} style={{ width: size, height: size, borderRadius: size / 2 }} contentFit="cover" />;
  }
  return (
    <View style={[styles.avatar, { width: size, height: size, borderRadius: size / 2 }]}>
      <Text style={[styles.avatarText, { fontSize: size * 0.38 }]}>{initials}</Text>
    </View>
  );
}

export function IconBox({ name, size = 40, tone = "brand" }: { name: IconName; size?: number; tone?: "brand" | "warning" | "error" }) {
  const { colors } = useTheme();
  const bg = tone === "warning" ? colors.warningSoft : tone === "error" ? colors.errorSoft : colors.brandTertiary;
  const fg = tone === "warning" ? colors.warningText : tone === "error" ? colors.errorText : colors.onBrandTertiary;
  return (
    <View style={{ width: size, height: size, borderRadius: 10, backgroundColor: bg, alignItems: "center", justifyContent: "center" }}>
      <Ionicons name={name} size={size * 0.5} color={fg} />
    </View>
  );
}

export function Chip({ label, selected, onPress, testID }: { label: string; selected?: boolean; onPress: () => void; testID?: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <Pressable
      testID={testID}
      onPress={() => {
        Haptics.selectionAsync().catch(() => {});
        onPress();
      }}
      style={[
        styles.chip,
        selected ? { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary } : null,
      ]}
    >
      <Text style={[styles.chipText, { color: selected ? colors.onBrandPrimary : colors.onSurfaceSecondary }]}>{label}</Text>
    </Pressable>
  );
}

export function Field({ label, style, ...props }: TextInputProps & { label: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.fieldWrap}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput placeholderTextColor={colors.muted} style={[styles.input, props.multiline && styles.inputMulti, style]} {...props} />
    </View>
  );
}

export function SectionHeader({ title, action, onAction, testID }: { title: string; action?: string; onAction?: () => void; testID?: string }) {
  const styles = useStyles();
  return (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {action && (
        <Pressable testID={testID} onPress={onAction} hitSlop={12}>
          <Text style={styles.sectionAction}>{action}</Text>
        </Pressable>
      )}
    </View>
  );
}

export function Loading() {
  const { colors } = useTheme();
  return (
    <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 48 }} testID="loading-indicator">
      <ActivityIndicator color={colors.brandPrimary} size="large" />
    </View>
  );
}

export function EmptyState({ icon, title, subtitle, actionLabel, onAction, testID }: { icon: IconName; title: string; subtitle?: string; actionLabel?: string; onAction?: () => void; testID?: string }) {
  const styles = useStyles();
  return (
    <View style={styles.empty} testID={testID ?? "empty-state"}>
      <IconBox name={icon} size={64} />
      <Text style={styles.emptyTitle}>{title}</Text>
      {subtitle && <Text style={styles.emptySub}>{subtitle}</Text>}
      {actionLabel && onAction && <Button label={actionLabel} onPress={onAction} style={{ marginTop: 16 }} testID="empty-state-action" />}
    </View>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  const styles = useStyles();
  return (
    <View style={styles.empty} testID="error-state">
      <IconBox name="cloud-offline-outline" size={64} tone="error" />
      <Text style={styles.emptyTitle}>{message}</Text>
      <Button label="Retry" variant="secondary" onPress={onRetry} style={{ marginTop: 16 }} testID="error-retry-button" />
    </View>
  );
}

export function ConfirmSheet({
  visible,
  title,
  message,
  confirmLabel,
  onConfirm,
  onClose,
  loading,
}: {
  visible: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
  onClose: () => void;
  loading?: boolean;
}) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.scrim} onPress={onClose} testID="confirm-sheet-backdrop" />
      <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]} testID="confirm-sheet">
        <View style={styles.grabber} />
        <Text style={styles.sheetTitle}>{title}</Text>
        <Text style={styles.sheetMsg}>{message}</Text>
        <Button label={confirmLabel} variant="danger" loading={loading} onPress={onConfirm} testID="confirm-sheet-confirm" />
        <Button label="Cancel" variant="ghost" onPress={onClose} style={{ marginTop: 8 }} testID="confirm-sheet-cancel" />
      </View>
    </Modal>
  );
}

const useStyles = makeStyles((c) => ({
  btn: {
    minHeight: 48,
    borderRadius: 12,
    paddingHorizontal: 20,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  btnText: { fontSize: 16, fontWeight: "600" },
  card: {
    backgroundColor: c.surface,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: c.border,
    shadowColor: "#000",
    shadowOpacity: 0.04,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, alignSelf: "flex-start" },
  badgeText: { fontSize: 12, fontWeight: "700" },
  avatar: { backgroundColor: c.brandSecondary, alignItems: "center", justifyContent: "center" },
  avatarText: { color: c.onBrandSecondary, fontWeight: "700" },
  chip: {
    height: 36,
    paddingHorizontal: 14,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.surface,
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  chipText: { fontSize: 14, fontWeight: "500" },
  fieldWrap: { marginBottom: 16 },
  fieldLabel: { fontSize: 13, fontWeight: "600", color: c.onSurfaceSecondary, marginBottom: 6 },
  input: {
    minHeight: 48,
    borderRadius: 12,
    backgroundColor: c.surfaceSecondary,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    color: c.onSurface,
  },
  inputMulti: { minHeight: 120, textAlignVertical: "top" },
  sectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 24, marginBottom: 12 },
  sectionTitle: { fontSize: 20, fontWeight: "700", color: c.onSurface, letterSpacing: -0.3 },
  sectionAction: { fontSize: 14, fontWeight: "600", color: c.brandPrimary },
  empty: { flex: 1, alignItems: "center", justifyContent: "center", padding: 32, gap: 8 },
  emptyTitle: { fontSize: 17, fontWeight: "600", color: c.onSurface, textAlign: "center", marginTop: 12 },
  emptySub: { fontSize: 14, color: c.muted, textAlign: "center", lineHeight: 20 },
  scrim: { flex: 1, backgroundColor: c.scrim },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 24, paddingTop: 12 },
  grabber: { width: 36, height: 5, borderRadius: 3, backgroundColor: c.borderStrong, alignSelf: "center", marginBottom: 16 },
  sheetTitle: { fontSize: 20, fontWeight: "700", color: c.onSurface, marginBottom: 8 },
  sheetMsg: { fontSize: 15, color: c.onSurfaceSecondary, marginBottom: 24, lineHeight: 21 },
}));
