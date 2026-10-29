"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore } from "react";

import { dictionaries, type Dictionary, type Locale } from "./dictionaries";

interface I18nValue {
  locale: Locale;
  dir: "ltr" | "rtl";
  t: Dictionary;
  setLocale: (l: Locale) => void;
  /** Translated label for an API enum key (source, stage, factor...), falling back to a humanized key. */
  label: (key: string | null | undefined) => string;
  /** Translated form-validation message; schema messages are dictionary keys. */
  vmsg: (msg: string | undefined) => string | undefined;
  /** Job event / live activity in the user's language (`data.t` template + `data.p` params), else `fallback`. */
  eventText: (data: unknown, fallback?: string | null) => string;
}

function humanize(key: string) {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Fill a `{param}` template; enum-like params (provider, platform, status, mode) are translated too. */
function renderEvent(t: Dictionary, data: unknown, fallback: string): string {
  const d = data && typeof data === "object" ? (data as { t?: unknown; p?: unknown }) : {};
  const template = typeof d.t === "string" ? t.events[d.t] : undefined;
  if (!template) return fallback;
  const params = d.p && typeof d.p === "object" ? (d.p as Record<string, unknown>) : {};
  const label = (k: string) => t.labels[k] ?? humanize(k);
  return template.replace(/\{(\w+)\}/g, (_, name: string) => {
    const v = params[name];
    if (v === null || v === undefined || v === "") return "—";
    const s = String(v);
    if (name === "provider" || name === "platform" || name === "mode") return label(s);
    if (name === "status") return t.status[s as keyof typeof t.status] ?? (t.labels[s] ?? s);
    if (name === "reason") return t.providerStatus[s as keyof typeof t.providerStatus] ?? s;
    return s;
  });
}

const I18nContext = createContext<I18nValue | null>(null);
const STORAGE_KEY = "lh-locale";

const listeners = new Set<() => void>();
let memoryLocale: Locale = "ar"; // used when localStorage is unavailable

function readLocale(): Locale {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return saved === "ar" || saved === "en" ? saved : memoryLocale;
  } catch {
    return memoryLocale;
  }
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  // Arabic is the default; the client switches to the saved locale after hydration.
  const locale = useSyncExternalStore(subscribe, readLocale, () => "ar" as Locale);

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
  }, [locale]);

  const setLocale = useCallback((l: Locale) => {
    memoryLocale = l;
    try {
      window.localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* storage unavailable */
    }
    listeners.forEach((cb) => cb());
  }, []);

  const value = useMemo<I18nValue>(() => {
    const t = dictionaries[locale];
    const validation = t.validation as Record<string, string>;
    return {
      locale,
      dir: locale === "ar" ? "rtl" : "ltr",
      t,
      setLocale,
      label: (key) => (key ? (t.labels[key] ?? humanize(key)) : "—"),
      // Unkeyed messages (zod defaults) are English; show a generic message in Arabic instead.
      vmsg: (msg) => (msg ? (validation[msg] ?? (locale === "ar" ? validation.invalid : msg)) : undefined),
      eventText: (data, fallback) => renderEvent(t, data, fallback ?? ""),
    };
  }, [locale, setLocale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside I18nProvider");
  return ctx;
}
