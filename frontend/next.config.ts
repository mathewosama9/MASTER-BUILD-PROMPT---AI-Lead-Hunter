import type { NextConfig } from "next";

// The browser always talks to the same origin (/api/*). Next proxies those requests to the FastAPI
// backend so session cookies stay first-party and no CORS is needed.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  // Next.js gzip buffers Server-Sent Events. Compression is done by the reverse proxy instead (see infrastructure/nginx).
  compress: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // The dashboard moved under /app when the public site took over "/"; keep old links (bookmarks, Telegram) working.
  async redirects() {
    // The agency "services" page was replaced by "who it's for" in the Rasd rebrand.
    const renamed = [{ source: "/services", destination: "/use-cases", permanent: true }];
    return renamed.concat(["campaigns", "leads", "settings", "suppression", "billing"].flatMap((section) => [
      { source: `/${section}`, destination: `/app/${section}`, permanent: false },
      { source: `/${section}/:path*`, destination: `/app/${section}/:path*`, permanent: false },
    ]));
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_INTERNAL_URL}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
