import { Platform } from "react-native";
import * as WebBrowser from "expo-web-browser";
import { fetch as expoFetch } from "expo/fetch";

export const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;
export const API_URL = `${BACKEND_URL}/api`;

let token: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setApiToken(t: string | null) {
  token = t;
}
export function getApiToken() {
  return token;
}
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${API_URL}${path}`, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && path !== "/auth/session") onUnauthorized?.();
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const msg = typeof data?.detail === "string" ? data.detail : "Something went wrong";
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export function authHeaders(): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function openCertificateFile(certId: string) {
  const url = `${API_URL}/files/${certId}?token=${encodeURIComponent(token ?? "")}`;
  if (Platform.OS === "web") {
    window.open(url, "_blank");
  } else {
    await WebBrowser.openBrowserAsync(url);
  }
}

export async function openDriveFile(fileId: string, space = "therapist") {
  await openLink(`${API_URL}/drive/shared/file/${fileId}?space=${space}&token=${encodeURIComponent(token ?? "")}`);
}

export async function openLink(url: string) {
  if (Platform.OS === "web") {
    window.open(url, "_blank");
  } else {
    await WebBrowser.openBrowserAsync(url);
  }
}

// Streams Server-Sent Events from POST /api/ai/ask. Calls onDelta for each text chunk.
export async function streamAsk(question: string, onDelta: (t: string) => void): Promise<void> {
  const res = await expoFetch(`${API_URL}/ai/ask`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok || !res.body) {
    if (res.status === 401) onUnauthorized?.();
    throw new ApiError(res.status, "The assistant is unavailable right now.");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const events = buf.split("\n\n");
    buf = events.pop() ?? "";
    for (const ev of events) {
      const line = ev.trim();
      if (!line.startsWith("data:")) continue;
      const data = JSON.parse(line.slice(5).trim());
      if (data.error) throw new ApiError(502, data.error);
      if (data.delta) onDelta(data.delta);
      if (data.done) return;
    }
  }
}
