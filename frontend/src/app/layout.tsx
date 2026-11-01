import type { Metadata, Viewport } from "next";
import { IBM_Plex_Sans_Arabic, Readex_Pro } from "next/font/google";

import { Providers } from "@/components/providers";
import { SITE_URL } from "@/lib/site";

import "./globals.css";

// Rasd brand fonts: Readex Pro for headings and IBM Plex Sans Arabic for text. Both cover Arabic and Latin.
const readex = Readex_Pro({ variable: "--font-readex", subsets: ["arabic", "latin"], weight: ["400", "500", "600", "700"], display: "swap" });
const plexArabic = IBM_Plex_Sans_Arabic({
  variable: "--font-plex-arabic",
  subsets: ["arabic", "latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: "رصد · Rasd", template: "%s · رصد" },
  description: "رصد يلاقي الشركات اللي محتاجة خدمتك، ويجمع أرقامها وواتسابها، ويقولك ليه كل واحدة محتاجاك.",
  applicationName: "Rasd",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#04110e" },
    { media: "(prefers-color-scheme: light)", color: "#f7f7f2" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ar" dir="rtl" suppressHydrationWarning className={`${readex.variable} ${plexArabic.variable} h-full antialiased`}>
      <body className="min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
