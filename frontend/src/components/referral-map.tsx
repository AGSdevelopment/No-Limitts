import { createElement } from "react";
import { Linking, Platform, View } from "react-native";
import { WebView } from "react-native-webview";

import { API_URL, getApiToken } from "@/src/api";

// Free OpenStreetMap of Referral Partners, rendered by the backend page (works on web, iOS and Android).
export function ReferralMap({ postcode, radius, height = 420 }: { postcode?: string; radius?: number | null; height?: number }) {
  const pc = postcode && /^\d{4}$/.test(postcode) ? postcode : "";
  const uri = `${API_URL}/referral-map?token=${encodeURIComponent(getApiToken() ?? "")}${pc ? `&postcode=${pc}${radius != null ? `&radius=${radius}` : ""}` : ""}`;
  return (
    <View style={{ height, borderRadius: 16, overflow: "hidden" }} testID="referral-map">
      {Platform.OS === "web"
        ? createElement("iframe", { src: uri, style: { width: "100%", height: "100%", border: 0 }, title: "Referral partners map" })
        : (
          <WebView
            source={{ uri }}
            style={{ flex: 1 }}
            originWhitelist={["*"]}
            setSupportMultipleWindows={false}
            onShouldStartLoadWithRequest={(req) => {
              // Directions, phone and website links open in the phone's own apps, not inside the map
              if (req.url.startsWith(`${API_URL}/referral-map`) || req.url === "about:blank") return true;
              Linking.openURL(req.url).catch(() => {});
              return false;
            }}
          />
        )}
    </View>
  );
}
