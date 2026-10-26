import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Platform } from "react-native";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

import { api, setApiToken, setUnauthorizedHandler } from "@/src/api";
import { queryClient } from "@/src/query-client";
import { storage } from "@/src/utils/storage";

WebBrowser.maybeCompleteAuthSession();

const TOKEN_KEY = "auth_token";

export type User = {
  user_id: string;
  email: string;
  name: string;
  picture?: string | null;
  role: "admin" | "employee";
  job_title?: string;
};

type AuthState = {
  user: User | null;
  loading: boolean;
  signingIn: boolean;
  error: string | null;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

function extractSessionId(url: string | null | undefined): string | null {
  if (!url) return null;
  const m = url.match(/[?#&]session_id=([^&#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [signingIn, setSigningIn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sent = useRef(new Set<string>());

  const clear = useCallback(async () => {
    await storage.secureRemove(TOKEN_KEY);
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
          setUser(await api<User>("/auth/me"));
        } catch {
          await clear();
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
    const authUrl = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
    if (Platform.OS === "web") {
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
    } finally {
      sub.remove();
    }
  }, [exchange]);

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
    <AuthContext.Provider value={{ user, loading, signingIn, error, signIn, signOut, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
