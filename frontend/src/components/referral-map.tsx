import { createElement } from "react";
import { Platform, View } from "react-native";
import { WebView } from "react-native-webview";

import { API_URL, getApiToken } from "@/src/api";

// Free OpenStreetMap of Referral Partners, rendered by the backend page (works on web, iOS and Android).
export function ReferralMap({ postcode, height = 420 }: { postcode?: string; height?: number }) {
  const pc = postcode && /^\d{4}$/.test(postcode) ? postcode : "";
  const uri = `${API_URL}/referral-map?token=${encodeURIComponent(getApiToken() ?? "")}${pc ? `&postcode=${pc}` : ""}`;
  return (
    <View style={{ height, borderRadius: 16, overflow: "hidden" }} testID="referral-map">
      {Platform.OS === "web"
        ? createElement("iframe", { src: uri, style: { width: "100%", height: "100%", border: 0 }, title: "Referral partners map" })
        : <WebView source={{ uri }} style={{ flex: 1 }} originWhitelist={["*"]} />}
    </View>
  );
}
