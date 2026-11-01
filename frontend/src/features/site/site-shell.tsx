"use client";

import { useQuery } from "@tanstack/react-query";
import { Languages, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import { Lockup } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n/provider";
import { API_BASE } from "@/lib/api";
import { cn } from "@/lib/utils";

import { ForwardArrow } from "./parts";

const LINKS = [
  { href: "/how-it-works", key: "howItWorks" },
  { href: "/use-cases", key: "useCases" },
  { href: "/pricing", key: "pricing" },
  { href: "/contact", key: "contact" },
] as const;

/**
 * Signed-in visitors get "Open dashboard" instead of sign-in/trial. Probed with a plain fetch because api()
 * sends a 401 to the login page, and here a 401 just means "visitor".
 */
export function useSignedIn() {
  const probe = useQuery({
    queryKey: ["site-signed-in"],
    queryFn: async () => (await fetch(`${API_BASE}/auth/me`, { credentials: "same-origin" })).ok,
    staleTime: 60_000,
    retry: false,
  });
  return probe.data === true;
}

function LangToggle({ className }: { className?: string }) {
  const { locale, setLocale, t } = useI18n();
  return (
    <button
      type="button"
      onClick={() => setLocale(locale === "en" ? "ar" : "en")}
      className={cn("inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground", className)}
      aria-label={t.common.language}
    >
      <Languages className="size-4" aria-hidden /> {locale === "en" ? "العربية" : "English"}
    </button>
  );
}

function SiteHeader() {
  const { t, locale } = useI18n();
  const pathname = usePathname();
  const signedIn = useSignedIn();
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const s = t.site.nav;

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const cta = signedIn ? (
    <Button asChild variant="ink" size="sm">
      <Link href="/app">{s.openApp}</Link>
    </Button>
  ) : (
    <>
      <Link href="/login" className="text-sm font-medium text-muted-foreground hover:text-foreground">
        {s.login}
      </Link>
      <Button asChild variant="ink" size="sm" className="rounded-full px-4">
        <Link href="/register">
          {s.startTrial} <ForwardArrow />
        </Link>
      </Button>
    </>
  );

  return (
    <header
      className={cn(
        "sticky top-0 z-40 transition-colors",
        scrolled || open ? "border-b bg-background/85 backdrop-blur-md" : "border-b border-transparent bg-transparent",
      )}
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-8 px-4 md:px-6">
        <Link href="/" aria-label={t.appName}>
          <Lockup locale={locale} markClassName="size-8" />
        </Link>
        <nav className="hidden items-center gap-6 md:flex" aria-label={t.common.mainNav}>
          {LINKS.map(({ href, key }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "text-sm font-medium transition-colors hover:text-foreground",
                  active ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {s[key]}
              </Link>
            );
          })}
        </nav>
        <div className="ms-auto hidden items-center gap-5 md:flex">
          <LangToggle />
          {cta}
        </div>
        <button
          type="button"
          className="ms-auto rounded-md p-2 md:hidden"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-label={s.menu}
        >
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </div>
      {open ? (
        <div className="border-t px-4 pb-5 pt-3 md:hidden">
          <nav className="flex flex-col gap-1" aria-label={t.common.mainNav}>
            {[{ href: "/", key: "home" } as const, ...LINKS].map(({ href, key }) => (
              <Link key={href} href={href} onClick={() => setOpen(false)} className="rounded-md px-2 py-2.5 font-medium hover:bg-muted">
                {s[key]}
              </Link>
            ))}
          </nav>
          <div className="mt-4 flex flex-wrap items-center gap-4">
            {cta}
            <LangToggle className="ms-auto" />
          </div>
        </div>
      ) : null}
    </header>
  );
}

const noopSubscribe = () => () => {};

function SiteFooter() {
  const { t, locale } = useI18n();
  const f = t.site.footer;
  // The current year is read in the browser only: prerendered HTML must not bake in the build date.
  const year = useSyncExternalStore(
    noopSubscribe,
    () => new Date().getFullYear(),
    () => null,
  );
  const col = "mb-4 text-xs font-semibold uppercase tracking-wide text-paper";
  const link = "hover:text-paper";
  return (
    <footer className="bg-ink-950 text-mist-300">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 md:grid-cols-4 md:px-6">
        <div className="md:col-span-2">
          <Lockup locale={locale} textClassName="text-paper" />
          <p className="mt-5 max-w-md text-sm leading-relaxed">{f.tagline}</p>
          <p className="mt-3 text-xs text-mist-500">{f.madeFor}</p>
        </div>
        <div>
          <p className={col}>{f.product}</p>
          <ul className="space-y-2.5 text-sm">
            <li>
              <Link href="/how-it-works" className={link}>
                {t.site.nav.howItWorks}
              </Link>
            </li>
            <li>
              <Link href="/use-cases" className={link}>
                {t.site.nav.useCases}
              </Link>
            </li>
            <li>
              <Link href="/pricing" className={link}>
                {t.site.nav.pricing}
              </Link>
            </li>
            <li>
              <Link href="/register" className={link}>
                {t.site.nav.startTrial}
              </Link>
            </li>
          </ul>
        </div>
        <div>
          <p className={col}>{f.resources}</p>
          <ul className="space-y-2.5 text-sm">
            <li>
              <Link href="/contact" className={link}>
                {t.site.nav.contact}
              </Link>
            </li>
            <li>
              <Link href="/login" className={link}>
                {t.site.nav.login}
              </Link>
            </li>
            <li>
              <Link href="/privacy" className={link}>
                {f.privacy}
              </Link>
            </li>
            <li>
              <Link href="/terms" className={link}>
                {f.terms}
              </Link>
            </li>
          </ul>
        </div>
      </div>
      <div className="border-t border-white/10">
        <p className="mx-auto max-w-6xl px-4 py-6 text-xs md:px-6">
          {f.rights.replace("{year}", year ? String(year) : "").replace("  ", " ")}
        </p>
      </div>
    </footer>
  );
}

export function SiteShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <SiteHeader />
      <main className="flex-1">{children}</main>
      <SiteFooter />
    </div>
  );
}
