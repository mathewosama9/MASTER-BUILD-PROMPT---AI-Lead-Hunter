/**
 * Links built from scraped data. Only real http(s) URLs become an `href`; anything else (`javascript:`, `data:`,
 * relative junk) returns null so the caller renders plain text instead of a clickable link.
 */
export function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

/** wa.me chat link for a phone number, with the ready first message pre-filled when there is one. */
export function whatsappUrl(phone: string, message?: string | null): string | null {
  const digits = phone.replace(/\D/g, "");
  if (!digits) return null;
  return message ? `https://wa.me/${digits}?text=${encodeURIComponent(message)}` : `https://wa.me/${digits}`;
}

/** A LinkedIn personal profile (`https://*.linkedin.com/in/...`), else null. */
export function linkedinProfileUrl(value: string | null | undefined): string | null {
  const safe = safeHttpUrl(value);
  if (!safe) return null;
  const url = new URL(safe);
  const host = url.hostname.toLowerCase();
  const isLinkedin = host === "linkedin.com" || host.endsWith(".linkedin.com");
  return url.protocol === "https:" && isLinkedin && url.pathname.startsWith("/in/") ? url.href : null;
}
