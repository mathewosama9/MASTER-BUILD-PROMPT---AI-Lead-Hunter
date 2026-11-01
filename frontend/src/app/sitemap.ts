import type { MetadataRoute } from "next";

import { PUBLIC_PATHS, SITE_URL, USE_CASE_SLUGS } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  const pages: MetadataRoute.Sitemap = PUBLIC_PATHS.map((path) => ({
    url: `${SITE_URL}${path}`,
    changeFrequency: path === "/" || path === "/pricing" ? "weekly" : "monthly",
    priority: path === "/" ? 1 : 0.7,
  }));
  return [
    ...pages,
    ...USE_CASE_SLUGS.map((slug) => ({
      url: `${SITE_URL}/use-cases/${slug}`,
      changeFrequency: "monthly" as const,
      priority: 0.6,
    })),
  ];
}
