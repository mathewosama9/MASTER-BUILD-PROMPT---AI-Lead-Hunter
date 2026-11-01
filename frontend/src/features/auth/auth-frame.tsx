"use client";

import { Languages } from "lucide-react";
import Link from "next/link";

import { Lockup } from "@/components/brand/logo";
import { LeadsTableMockup } from "@/features/site/mockups";
import { RadarBackdrop } from "@/features/site/motion";
import { useI18n } from "@/i18n/provider";
import { cn } from "@/lib/utils";

/** Split layout shared by sign-in, sign-up and the account pages: the form on one side, the product on the other. */
export function AuthFrame({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  const { t, locale, setLocale } = useI18n();
  const h = t.site.home;
  return (
    <div className="grid min-h-screen bg-background lg:grid-cols-[1fr_1.05fr]">
      <div className="flex flex-col px-5 py-6 md:px-12">
        <div className="flex items-center justify-between">
          <Link href="/" aria-label={t.appName}>
            <Lockup locale={locale} />
          </Link>
          <button
            type="button"
            onClick={() => setLocale(locale === "en" ? "ar" : "en")}
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <Languages className="size-4" aria-hidden /> {locale === "en" ? "العربية" : "English"}
          </button>
        </div>
        <div className="flex flex-1 items-center justify-center py-10">
          <div className={cn("w-full", wide ? "max-w-md" : "max-w-sm")}>{children}</div>
        </div>
      </div>
      <aside className="relative hidden flex-col justify-center overflow-hidden bg-ink-900 p-12 text-paper lg:flex xl:p-16">
        <RadarBackdrop onDark className="-bottom-[28rem] -end-[20rem] size-[56rem]" />
        <div className="relative max-w-lg">
          <p className="font-display text-3xl font-bold leading-tight tracking-tight xl:text-4xl">
            {h.title} <span className="text-signal-400">{h.titleHighlight}</span>
          </p>
          <p className="mt-4 leading-relaxed text-mist-300">{h.subtitle}</p>
        </div>
        <LeadsTableMockup className="relative mt-10 max-w-lg" />
      </aside>
    </div>
  );
}
