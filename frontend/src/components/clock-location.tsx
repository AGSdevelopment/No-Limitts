// Clock-in location: explains why before the system prompt, handles denied / blocked (Open Settings) and never blocks clocking in.
import { useRef, useState } from "react";
import { Linking, Platform } from "react-native";
import * as Location from "expo-location";

import { Sheet } from "@/src/components/participant-sheets";
import { Button } from "@/src/components/ui";

export type Fix = { lat: number; lng: number; accuracy: number | null };
type Ask = "explain" | "blocked" | null;

async function readFix(): Promise<Fix | null> {
  try {
    const pos = await Promise.race([
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }),
      new Promise<null>((r) => setTimeout(() => r(null), 12000)),
    ]);
    const p = pos ?? (Platform.OS === "web" ? null : await Location.getLastKnownPositionAsync());
    return p ? { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy ?? null } : null;
  } catch {
    return null;
  }
}

export function useClockLocation() {
  const [ask, setAsk] = useState<Ask>(null);
  const done = useRef<((v: Fix | null) => void) | null>(null);

  const finish = (v: Fix | null) => {
    setAsk(null);
    done.current?.(v);
    done.current = null;
  };

  const getFix = async (): Promise<Fix | null> => {
    let perm: Location.PermissionResponse;
    try {
      perm = await Location.getForegroundPermissionsAsync();
    } catch {
      return null;
    }
    if (perm.granted) return readFix();
    return new Promise((resolve) => {
      done.current = resolve;
      setAsk(perm.canAskAgain ? "explain" : "blocked");
    });
  };

  const share = async () => {
    const r = await Location.requestForegroundPermissionsAsync().catch(() => null);
    if (r?.granted) {
      setAsk(null);
      finish(await readFix());
    } else if (r && !r.canAskAgain) {
      setAsk("blocked");
    } else {
      finish(null);
    }
  };

  const sheet = (
    <Sheet visible={!!ask} onClose={() => finish(null)} testID="clock-location-sheet"
      title={ask === "blocked" ? "Location is turned off for No Limitts" : "Share your location to clock in?"}
      sub={ask === "blocked"
        ? Platform.OS === "web"
          ? "Your browser is blocking location for this site. Allow it from the lock icon next to the web address, then try again. You can still clock in without it, but Rosters will review the times."
          : "Turn location on in Settings so your clock-ins are confirmed automatically. You can still clock in without it, but Rosters will review the times."
        : "We check you're at the participant's address when you clock in. Your location is only read at that moment, never tracked."}>
      {ask === "blocked" ? (
        Platform.OS === "web" ? null : <Button label="Open Settings" icon="settings-outline" onPress={() => { Linking.openSettings(); finish(null); }} testID="clock-location-settings" />
      ) : (
        <Button label="Share location" icon="location-outline" onPress={share} testID="clock-location-share" />
      )}
      <Button label="Clock in without location" variant="ghost" onPress={() => finish(null)} testID="clock-location-skip" />
    </Sheet>
  );

  return { getFix, sheet };
}
