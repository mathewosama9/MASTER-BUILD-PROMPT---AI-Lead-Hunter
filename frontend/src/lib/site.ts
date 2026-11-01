import type { Metadata } from "next";

import { dictionaries } from "@/i18n/dictionaries";

/** Public origin of the site (FRONTEND_URL in docker compose). Used for canonical/OG URLs, sitemap and robots. */
export const SITE_URL = (process.env.SITE_URL ?? "http://localhost:3000").replace(/\/$/, "");

export const PUBLIC_PATHS = ["/", "/how-it-works", "/use-cases", "/pricing", "/contact", "/register", "/privacy", "/terms"] as const;

/** One public page per use case: /use-cases/<key>. */
export const USE_CASE_SLUGS = dictionaries.en.site.useCases.items.map((x) => x.key);

/** Arabic is the default language, so page metadata is Arabic; the page itself switches language on the client. */
export function pageMetadata(path: string, title: string, description: string): Metadata {
  return {
    title: { absolute: title },
    description,
    alternates: { canonical: path },
    openGraph: {
      title,
      description,
      url: path,
      siteName: "رصد · Rasd",
      locale: "ar_SA",
      alternateLocale: ["en_US"],
      type: "website",
    },
    twitter: { card: "summary_large_image", title, description },
  };
}

export const ar = dictionaries.ar.site;
