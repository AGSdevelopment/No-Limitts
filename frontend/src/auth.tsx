import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Platform } from "react-native";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

import { API_URL, api, ApiError, setApiToken, setUnauthorizedHandler } from "@/src/api";
import { queryClient } from "@/src/query-client";
import { storage } from "@/src/utils/storage";

WebBrowser.maybeCompleteAuthSession();

const TOKEN_KEY = "auth_token";
const USER_KEY = "auth_user";

export type User = {
  user_id: string;
  email: string;
  name: string;
  picture?: string | null;
  role: "admin" | "employee";
  executive?: boolean;
  job_title?: string;
  start_date?: string | null;
  user_type?: "executive" | "admin" | "support_office" | "support_worker" | "hr" | "support_coordinator";
  must_change_password?: boolean;
};

type AuthState = {
  user: User | null;
  loading: boolean;
  signingIn: boolean;
  error: string | null;
  signIn: () => Promise<void>;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  setSignedInUser: (u: User) => void;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

function urlParam(url: string | null | undefined, name: string): string | null {
  if (!url) return null;
  const m = url.match(new RegExp(`[?#&]${name}=([^&#]+)`));
  return m ? decodeURIComponent(m[1].replace(/\+/g, " ")) : null;
}
const extractSessionId = (url: string | null | undefined) => urlParam(url, "session_id");

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [signingIn, setSigningIn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sent = useRef(new Set<string>());

  const clear = useCallback(async () => {
    await storage.secureRemove(TOKEN_KEY);
    await storage.removeItem(USER_KEY);
    setApiToken(null);
    queryClient.clear();
    setUser(null);
  }, []);

  const exchange = useCallback(async (sessionId: string) => {
    if (sent.current.has(sessionId)) return false;
    sent.current.add(sessionId);
    setSigningIn(true);
    setError(null);
    try {
      const res = await api<{ session_token: string; user: User }>("/auth/session", {
        method: "POST",
        body: { session_id: sessionId },
      });
      await storage.secureSet(TOKEN_KEY, res.session_token);
      setApiToken(res.session_token);
      setUser(res.user);
      await storage.setItem(USER_KEY, res.user);
      if (Platform.OS === "web") {
        const { pathname, search, hash } = window.location;
        const params = new URLSearchParams(search);
        params.delete("session_id");
        const h = hash.replace(/(^#|&)session_id=[^&]*/, "").replace(/^#?&/, "#");
        const qs = params.toString();
        window.history.replaceState(window.history.state, "", pathname + (qs ? `?${qs}` : "") + (h === "#" ? "" : h));
      }
      return true;
    } catch {
      setError("Sign-in failed. Please try again.");
      return false;
    } finally {
      setSigningIn(false);
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clear();
    });
    let sub: { remove: () => void } | null = null;
    (async () => {
      let sid: string | null = null;
      if (Platform.OS === "web") {
        sid = extractSessionId(window.location.href);
        // Opened as a pop-up from an embedded preview: hand the one-time code back to the app window and close.
        if (sid && window.opener && !window.opener.closed) {
          try {
            window.opener.postMessage({ nlSession: sid }, window.location.origin);
            window.close();
            return;
          } catch {}
        }
        const err = urlParam(window.location.href, "auth_error");
        if (err) {
          setError(err);
          window.history.replaceState(window.history.state, "", window.location.pathname);
        }
      } else {
        sid = extractSessionId(await Linking.getInitialURL());
        sub = Linking.addEventListener("url", ({ url }) => {
          const s = extractSessionId(url);
          if (s) exchange(s);
        });
      }
      if (sid && (await exchange(sid))) {
        setLoading(false);
        return;
      }
      const saved = await storage.secureGet(TOKEN_KEY, null as string | null);
      if (saved) {
        setApiToken(saved);
        try {
          const me = await api<User>("/auth/me");
          setUser(me);
          await storage.setItem(USER_KEY, me);
        } catch (e: any) {
          // only sign out when the session is actually invalid; offline -> use the last known profile
          if (e instanceof ApiError && e.status === 401) await clear();
          else setUser(await storage.getItem(USER_KEY, null as User | null));
        }
      }
      setLoading(false);
    })();
    return () => {
      sub?.remove();
      setUnauthorizedHandler(null);
    };
  }, [clear, exchange]);

  const signIn = useCallback(async () => {
    setError(null);
    const redirectUrl = Platform.OS === "web" ? window.location.origin + "/" : Linking.createURL("");
    const authUrl = `${API_URL}/auth/microsoft/start?redirect=${encodeURIComponent(redirectUrl)}`;
    if (Platform.OS === "web") {
      // Microsoft refuses to load inside a frame (e.g. the Emergent preview panel), so sign in through a pop-up there
      if (window.self !== window.top) {
        const onMsg = (e: MessageEvent) => {
          if (e.origin !== window.location.origin || !e.data?.nlSession) return;
          window.removeEventListener("message", onMsg);
          exchange(e.data.nlSession);
        };
        window.addEventListener("message", onMsg);
        if (!window.open(authUrl, "nl-microsoft-login", "width=520,height=720")) {
          window.removeEventListener("message", onMsg);
          setError("Allow pop-ups for this page to sign in with Microsoft, or open the app in its own browser tab.");
        }
        return;
      }
      window.location.href = authUrl;
      return;
    }
    let captured: string | null = null;
    const sub = Linking.addEventListener("url", ({ url }) => {
      captured = url;
    });
    try {
      const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
      const url = (result.type === "success" ? result.url : null) ?? captured ?? (await Linking.getInitialURL());
      const sid = extractSessionId(url);
      if (sid) await exchange(sid);
      else if (urlParam(url, "auth_error")) setError(urlParam(url, "auth_error"));
    } finally {
      sub.remove();
    }
  }, [exchange]);

  const signInWithPassword = useCallback(async (email: string, password: string) => {
    setError(null);
    setSigningIn(true);
    try {
      const res = await api<{ session_token: string; user: User }>("/auth/login", { method: "POST", body: { email, password } });
      await storage.secureSet(TOKEN_KEY, res.session_token);
      setApiToken(res.session_token);
      setUser(res.user);
      await storage.setItem(USER_KEY, res.user);
    } catch (e: any) {
      setError(e.message || "Sign-in failed. Please try again.");
    } finally {
      setSigningIn(false);
    }
  }, []);

  const setSignedInUser = useCallback((u: User) => {
    setUser(u);
    storage.setItem(USER_KEY, u);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {}
    await clear();
  }, [clear]);

  const refreshUser = useCallback(async () => {
    try {
      setUser(await api<User>("/auth/me"));
    } catch {}
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, signingIn, error, signIn, signInWithPassword, setSignedInUser, signOut, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
