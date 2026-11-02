import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(n: number | null | undefined, locale = "en") {
  if (n === null || n === undefined) return "—";
  // Latin digits in both locales keep numbers consistent with charts and exports.
  return new Intl.NumberFormat(locale === "ar" ? "ar-SA-u-nu-latn" : "en-US").format(n);
}

export function formatMoney(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return `$${n.toFixed(n < 1 ? 3 : 2)}`;
}

/** A store price, e.g. "$15" or "$15.50" (the store sells in US dollars). */
export function formatPrice(amount: number | string, currency = "USD") {
  const n = Number(amount);
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return `${n} ${currency}`;
  }
}

export function formatDate(iso: string | null | undefined, locale = "en") {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(locale === "ar" ? "ar" : "en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

export function relativeTime(iso: string, locale = "en") {
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  return rtf.format(Math.round(diff / 86400), "day");
}

export function humanize(key: string | null | undefined) {
  if (!key) return "—";
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Resolve a post-login `next` value to a same-origin path, or `fallback` for anything else. */
export function safeNextPath(next: string | null | undefined, origin: string, fallback = "/") {
  if (!next) return fallback;
  let url: URL;
  try {
    url = new URL(next, origin);
  } catch {
    return fallback;
  }
  if (url.origin !== origin) return fallback;
  return url.pathname + url.search;
}
