import { Pressable, View } from "react-native";
import { Text } from "@/src/components/text";
import { Image } from "expo-image";

import { openLink } from "@/src/api";
import { IconName, Ionicons, timeAgo } from "@/src/components/ui";
import { makeStyles, useTheme } from "@/src/theme";

// Official brand colours stay the same in every theme.
export const SOCIAL_BRAND: Record<string, { icon: IconName; color: string }> = {
  instagram: { icon: "logo-instagram", color: "#E1306C" },
  facebook: { icon: "logo-facebook", color: "#1877F2" },
  linkedin: { icon: "logo-linkedin", color: "#0A66C2" },
};

export function SocialPost({ item }: { item: any }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const brand = SOCIAL_BRAND[item.source] ?? SOCIAL_BRAND.facebook;
  return (
    <Pressable testID={`social-post-${item.update_id}`} onPress={() => item.link && openLink(item.link)} style={styles.post}>
      <View style={styles.postHead}>
        <Ionicons name={brand.icon} size={18} color={brand.color} />
        <Text style={styles.postMeta}>{item.author_name} · {timeAgo(item.created_at)}</Text>
      </View>
      {!!item.image_url && <Image source={{ uri: item.image_url }} style={styles.postImage} contentFit="cover" transition={200} />}
      {!!item.body && <Text style={styles.postText} numberOfLines={6}>{item.body}</Text>}
      {!!item.link && (
        <View style={styles.viewRow}>
          <Text style={styles.viewLink}>View post</Text>
          <Ionicons name="arrow-forward" size={14} color={colors.brandPrimary} />
        </View>
      )}
    </Pressable>
  );
}

const useStyles = makeStyles((c) => ({
  post: { backgroundColor: c.surface, borderRadius: 16, padding: 14, gap: 10 },
  postHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  postMeta: { fontSize: 13, color: c.muted, flex: 1 },
  postImage: { width: "100%", aspectRatio: 1, borderRadius: 12, backgroundColor: c.surfaceSecondary },
  postText: { fontSize: 15, color: c.onSurface, lineHeight: 22 },
  viewRow: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 32 },
  viewLink: { fontSize: 14, fontWeight: "600", color: c.brandPrimary },
}));
