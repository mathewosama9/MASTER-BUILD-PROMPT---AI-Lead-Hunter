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
  /** A data provider as customers see it: its generic group ("Business listings"), never the provider's name. */
  source: (key: string | null | undefined) => string;
  /** Translated form-validation message; schema messages are dictionary keys. */
  vmsg: (msg: string | undefined) => string | undefined;
  /** Job event / live activity in the user's language (`data.t` template + `data.p` params), else `fallback`. */
  eventText: (data: unknown, fallback?: string | null) => string;
}

/** Provider key → customer-facing group. Keys not listed (import, manual, demo, heuristic) keep their own label. */
const SOURCE_GROUP: Record<string, keyof Dictionary["sourceGroups"]> = {
  google_maps: "listings",
  osm: "listings",
  directories: "listings",
  brave: "web",
  social_search: "web",
  linkedin_search: "web",
  person_search: "web",
  website: "website",
  structured_data: "website",
  instagram: "social",
  facebook: "social",
  tiktok: "social",
  snapchat: "social",
  linkedin: "social",
  x: "social",
  social_discovery: "social",
  hunter: "contacts",
  apollo: "contacts",
  lusha: "contacts",
  decision_maker: "contacts",
  deepseek: "ai",
  anthropic: "ai",
  openai: "ai",
  perplexity: "ai",
  gemini: "ai",
  ai_research: "ai",
};

function sourceName(t: Dictionary, key: string): string {
  // Combined provenance such as "website+brave" lists each group once.
  const parts = key.split("+").map((k) => {
    const g = SOURCE_GROUP[k];
    return g ? t.sourceGroups[g] : (t.labels[k] ?? humanize(k));
  });
  return [...new Set(parts)].join(" + ");
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
  return template.replace(/\{(\w+)\}/g, (_, name: string) => {
    const v = params[name];
    if (v === null || v === undefined || v === "") return "—";
    const s = String(v);
    if (name === "provider") return sourceName(t, s);
    if (name === "platform" || name === "mode") return t.labels[s] ?? humanize(s);
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

/** Has this browser a language of its own (picked by the user), or is it still on the default? */
export function hasSavedLocale(): boolean {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return saved === "ar" || saved === "en";
  } catch {
    return false;
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
      source: (key) => (key ? sourceName(t, key) : "—"),
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
