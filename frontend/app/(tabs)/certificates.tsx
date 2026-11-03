import { useState } from "react";
import { FlatList, Pressable, RefreshControl, ScrollView, View } from "react-native";
import { Text } from "@/src/components/text";
import { useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, openCertificateFile } from "@/src/api";
import { useAuth } from "@/src/auth";
import { TabHeader } from "@/src/components/header";
import { useToast } from "@/src/components/toast";
import { Chip, ConfirmSheet, EmptyState, ErrorState, IconBox, Ionicons, Loading, StatusBadge, formatDate, tap } from "@/src/components/ui";
import { usesNativeTabs } from "@/src/navigation";
import { makeStyles, useTheme } from "@/src/theme";

export default function Certificates() {
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const { colors } = useTheme();
  const toast = useToast();
  const qc = useQueryClient();
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [toDelete, setToDelete] = useState<any>(null);
  const [deleting, setDeleting] = useState(false);
  const q = useQuery<any[]>({ queryKey: ["certificates", scope], queryFn: () => api(`/certificates?scope=${scope}`) });
  const certs = q.data ?? [];
  const counts = {
    expired: certs.filter((c) => c.status === "expired").length,
    expiring: certs.filter((c) => c.status === "expiring").length,
    valid: certs.filter((c) => c.status === "valid").length,
  };
  const bottomChrome = usesNativeTabs ? insets.bottom : 0;

  const remove = async () => {
    setDeleting(true);
    try {
      await api(`/certificates/${toDelete.cert_id}`, { method: "DELETE" });
      toast("Certificate removed");
      qc.invalidateQueries({ queryKey: ["certificates"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setToDelete(null);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <View style={styles.root} testID="certificates-screen">
      <TabHeader title="Certificates" />
      {user?.role === "admin" && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow} contentContainerStyle={styles.chipContent}>
          <Chip label="My certificates" selected={scope === "mine"} onPress={() => setScope("mine")} testID="cert-scope-mine" />
          <Chip label="Whole team" selected={scope === "all"} onPress={() => setScope("all")} testID="cert-scope-all" />
        </ScrollView>
      )}
      {q.isLoading ? (
        <Loading />
      ) : q.isError ? (
        <ErrorState message="Could not fetch certificates." onRetry={() => q.refetch()} />
      ) : (
        <FlatList
          data={certs}
          keyExtractor={(c) => c.cert_id}
          contentContainerStyle={{ padding: 16, paddingBottom: bottomChrome + 96, gap: 12, flexGrow: 1 }}
          refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => q.refetch()} tintColor={colors.brandPrimary} />}
          ListHeaderComponent={
            certs.length > 0 ? (
              <View style={styles.summary} testID="cert-summary">
                {(
                  [
                    ["expired", "Expired", colors.errorText],
                    ["expiring", "Expiring", colors.warningText],
                    ["valid", "Valid", colors.successText],
                  ] as const
                ).map(([k, label, color]) => (
                  <View key={k} style={styles.summaryItem}>
                    <Text style={[styles.summaryNum, { color }]} testID={`cert-count-${k}`}>{counts[k]}</Text>
                    <Text style={styles.summaryLabel}>{label}</Text>
                  </View>
                ))}
              </View>
            ) : null
          }
          ListEmptyComponent={
            <EmptyState
              icon="ribbon-outline"
              title="No certificates uploaded yet."
              subtitle="Upload your training certificates and we'll count down from 60 days before they expire."
              actionLabel={scope === "mine" ? "Upload certificate" : undefined}
              onAction={() => router.push("/upload-certificate")}
            />
          }
          renderItem={({ item }) => (
            <Pressable
              testID={`cert-card-${item.cert_id}`}
              onPress={() => openCertificateFile(item.cert_id)}
              style={({ pressed }) => [styles.card, item.status !== "valid" && { borderColor: item.status === "expired" ? colors.error : colors.warning }, pressed && { opacity: 0.85 }]}
            >
              <IconBox
                name={item.content_type?.includes("pdf") ? "document-text" : "image"}
                tone={item.status === "expired" ? "error" : item.status === "expiring" ? "warning" : "brand"}
                size={44}
              />
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={styles.title} numberOfLines={1}>{item.title}</Text>
                {scope === "all" && <Text style={styles.sub}>{item.owner_name}</Text>}
                {!!item.issuer && <Text style={styles.sub} numberOfLines={1}>{item.issuer}</Text>}
                <View style={styles.metaRow}>
                  <StatusBadge status={item.status} testID={`cert-status-${item.cert_id}`} />
                  {!!item.drive_link && <Ionicons name="logo-microsoft" size={14} color={colors.muted} testID={`cert-drive-${item.cert_id}`} />}
                  <Text style={styles.sub}>
                    {item.status === "expired"
                      ? `Expired ${formatDate(item.expiry_date)}`
                      : item.status === "expiring"
                        ? `${item.days_left} days left`
                        : `Expires ${formatDate(item.expiry_date)}`}
                  </Text>
                </View>
              </View>
              {(item.owner_id === user?.user_id || user?.role === "admin") && (
                <Pressable testID={`cert-delete-${item.cert_id}`} hitSlop={10} onPress={() => setToDelete(item)} style={styles.trash}>
                  <Ionicons name="trash-outline" size={20} color={colors.muted} />
                </Pressable>
              )}
            </Pressable>
          )}
        />
      )}
      <Pressable
        testID="cert-upload-fab"
        onPress={() => {
          tap();
          router.push("/upload-certificate");
        }}
        style={({ pressed }) => [styles.fab, { bottom: bottomChrome + 16 }, pressed && { transform: [{ scale: 0.95 }] }]}
      >
        <Ionicons name="cloud-upload" size={22} color={colors.onBrandPrimary} />
        <Text style={styles.fabText}>Upload</Text>
      </Pressable>
      <ConfirmSheet
        visible={!!toDelete}
        title="Remove certificate?"
        message={`"${toDelete?.title ?? ""}" will be removed from your records.`}
        confirmLabel="Remove"
        loading={deleting}
        onConfirm={remove}
        onClose={() => setToDelete(null)}
      />
    </View>
  );
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.background },
  chipRow: { flexGrow: 0, height: 56, backgroundColor: c.surface },
  chipContent: { paddingHorizontal: 16, gap: 8, alignItems: "center" },
  summary: { flexDirection: "row", backgroundColor: c.surface, borderRadius: 16, padding: 16, marginBottom: 4 },
  summaryItem: { flex: 1, alignItems: "center" },
  summaryNum: { fontSize: 24, fontWeight: "700" },
  summaryLabel: { fontSize: 12, color: c.muted, fontWeight: "600", marginTop: 2 },
  card: { flexDirection: "row", gap: 12, alignItems: "center", backgroundColor: c.surface, borderRadius: 16, padding: 16, borderWidth: 1, borderColor: c.border },
  title: { fontSize: 16, fontWeight: "600", color: c.onSurface },
  sub: { fontSize: 13, color: c.muted },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4, flexWrap: "wrap" },
  trash: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  fab: {
    position: "absolute",
    right: 16,
    height: 56,
    paddingHorizontal: 20,
    borderRadius: 28,
    backgroundColor: c.brandPrimary,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    shadowColor: "#000",
    shadowOpacity: 0.2,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 6,
  },
  fabText: { color: c.onBrandPrimary, fontWeight: "700", fontSize: 16 },
}));
