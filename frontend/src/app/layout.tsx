import type { Metadata, Viewport } from "next";
import { Inter, Noto_Sans_Arabic, Rubik } from "next/font/google";

import { Providers } from "@/components/providers";

import "./globals.css";

// Neue Montreal (brand EN font) is loaded via @font-face from /public/fonts when the licensed files are
// present; Inter is the metric-compatible fallback. Arabic uses the brand's Rubik + Noto Sans Arabic.
const inter = Inter({ variable: "--font-inter", subsets: ["latin"], display: "swap" });
const rubik = Rubik({ variable: "--font-rubik", subsets: ["arabic", "latin"], weight: ["500", "700"], display: "swap" });
const notoArabic = Noto_Sans_Arabic({
  variable: "--font-noto-arabic",
  subsets: ["arabic"],
  weight: ["300", "400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "AI Lead Hunter", template: "%s · AI Lead Hunter" },
  description: "Intelligent B2B prospecting: discovery, enrichment, evidence-based AI analysis and lead scoring.",
  icons: { icon: "/logo.svg" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0e0f31" },
    { media: "(prefers-color-scheme: light)", color: "#f2f3ff" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="ar"
      dir="rtl"
      suppressHydrationWarning
      className={`${inter.variable} ${rubik.variable} ${notoArabic.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
