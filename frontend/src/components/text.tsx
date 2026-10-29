// App-wide Text / TextInput in the No Limitts brand font (Nunito). Picks the right font file for each
// fontWeight so bold text looks the same on iOS, Android and web.
import { StyleProp, StyleSheet, Text as RNText, TextInput as RNTextInput, TextInputProps, TextProps, TextStyle } from "react-native";

export const fonts = {
  "Nunito-400": require("@/assets/fonts/Nunito-400.ttf"),
  "Nunito-600": require("@/assets/fonts/Nunito-600.ttf"),
  "Nunito-700": require("@/assets/fonts/Nunito-700.ttf"),
  "Nunito-800": require("@/assets/fonts/Nunito-800.ttf"),
};

const FAMILY: Record<string, string> = {
  "100": "Nunito-400", "200": "Nunito-400", "300": "Nunito-400", "400": "Nunito-400", normal: "Nunito-400",
  "500": "Nunito-600", "600": "Nunito-600", "700": "Nunito-700", bold: "Nunito-700", "800": "Nunito-800", "900": "Nunito-800",
};

export function brandFont(style: StyleProp<TextStyle>): StyleProp<TextStyle> {
  const s = StyleSheet.flatten(style) || {};
  if (s.fontFamily) return style;
  return [style, { fontFamily: FAMILY[String(s.fontWeight ?? "400")] ?? "Nunito-400", fontWeight: "normal" }];
}

export function Text(props: TextProps & { ref?: React.Ref<RNText> }) {
  return <RNText {...props} style={brandFont(props.style)} />;
}

export function TextInput(props: TextInputProps & { ref?: React.Ref<RNTextInput> }) {
  return <RNTextInput {...props} style={brandFont(props.style)} />;
}
