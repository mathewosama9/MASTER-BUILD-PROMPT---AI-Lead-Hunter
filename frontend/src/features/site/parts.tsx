"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, ChevronDown, X } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

import { RadarBackdrop, Reveal } from "./motion";

export interface TrialTerms {
  trial_days: number;
  trial_credits: number;
  credits_per_contact: number;
}

/** Trial days/credits as the admin set them (never hard-coded on the page). */
export function useTrialTerms() {
  return useQuery({ queryKey: ["public-trial"], queryFn: () => api<TrialTerms>("/public/trial"), staleTime: 5 * 60_000 });
}

export function TrialNote({ className }: { className?: string }) {
  const { t } = useI18n();
  const { data } = useTrialTerms();
  if (!data) return <p className={cn("h-5", className)} />;
  return (
    <p className={className}>
      {t.site.trialNote.replace("{days}", String(data.trial_days)).replace("{credits}", String(data.trial_credits))}
    </p>
  );
}

/** Arrow pointing "forward" in the reading direction. */
export function ForwardArrow({ className }: { className?: string }) {
  const { dir } = useI18n();
  const Icon = dir === "rtl" ? ArrowLeft : ArrowRight;
  return <Icon className={className} aria-hidden />;
}

export function Section({
  id,
  className,
  children,
  tone = "plain",
}: {
  id?: string;
  className?: string;
  children: React.ReactNode;
  tone?: "plain" | "muted" | "ink";
}) {
  return (
    <section
      id={id}
      className={cn(
        "relative scroll-mt-20 px-4 py-20 md:px-6 md:py-28",
        tone === "muted" && "bg-sand-100 dark:bg-ink-900",
        tone === "ink" && "overflow-hidden bg-ink-900 text-paper",
        className,
      )}
    >
      <div className="relative mx-auto max-w-6xl">{children}</div>
    </section>
  );
}

/** Small pill above a heading, with the brand's lime "ping". */
export function Eyebrow({ children, onDark = false, className }: { children: React.ReactNode; onDark?: boolean; className?: string }) {
  return (
    <p
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium",
        onDark
          ? "border-white/15 bg-white/5 text-mist-300"
          : "border-rasd-600/20 bg-rasd-50 text-rasd-700 dark:bg-rasd-500/10 dark:text-rasd-300",
        className,
      )}
    >
      <span className="relative flex size-2">
        <span className="absolute inline-flex size-full animate-ping-slow rounded-full bg-signal-400" />
        <span className="relative inline-flex size-2 rounded-full bg-signal-500" />
      </span>
      {children}
    </p>
  );
}

export function Heading({
  title,
  subtitle,
  eyebrow,
  center = true,
  onDark = false,
}: {
  title: string;
  subtitle?: string;
  eyebrow?: string;
  center?: boolean;
  onDark?: boolean;
}) {
  return (
    <Reveal className={cn("mb-12 max-w-3xl md:mb-16", center && "mx-auto text-center")}>
      {eyebrow ? (
        <Eyebrow onDark={onDark} className="mb-4">
          {eyebrow}
        </Eyebrow>
      ) : null}
      <h2 className="text-3xl font-bold leading-tight tracking-tight text-balance md:text-[2.75rem]">{title}</h2>
      {subtitle ? (
        <p className={cn("mt-4 text-base leading-relaxed text-pretty md:text-lg", onDark ? "text-mist-300" : "text-muted-foreground")}>
          {subtitle}
        </p>
      ) : null}
    </Reveal>
  );
}

/** Hero for inner pages: eyebrow, title, subtitle over a faint grid and radar rings. */
export function PageHero({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  children?: React.ReactNode;
}) {
  return (
    <section className="relative overflow-hidden px-4 pb-16 pt-16 md:px-6 md:pb-24 md:pt-24">
      <div
        aria-hidden
        className="bg-grid pointer-events-none absolute inset-0 text-ink-900 [mask-image:radial-gradient(ellipse_at_top,black,transparent_70%)] dark:text-paper"
      />
      <RadarBackdrop className="-top-[30rem] left-1/2 size-[56rem] -translate-x-1/2" />
      <div className="relative mx-auto max-w-3xl text-center">
        <Eyebrow>{eyebrow}</Eyebrow>
        <h1 className="mt-6 text-4xl font-bold leading-[1.15] tracking-tight text-balance md:text-6xl">{title}</h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground text-pretty">{subtitle}</p>
        {children}
      </div>
    </section>
  );
}

/** One before → after row. Describes the workflow change only: no invented figures. */
export function BeforeAfter({ before, after, className }: { before: React.ReactNode; after: React.ReactNode; className?: string }) {
  const { t } = useI18n();
  return (
    <div className={cn("grid overflow-hidden rounded-2xl border bg-card md:grid-cols-2", className)}>
      <div className="flex gap-3 p-5 md:p-6">
        <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-rose-500/10 text-rose-600 dark:text-rose-300">
          <X className="size-3.5" aria-hidden />
        </span>
        <div>
          <p className="mb-1 text-xs font-semibold text-muted-foreground">{t.site.beforeLabel}</p>
          <div className="text-sm leading-relaxed text-foreground/75">{before}</div>
        </div>
      </div>
      <div className="flex gap-3 border-t bg-rasd-50/70 p-5 md:border-s md:border-t-0 md:p-6 dark:bg-rasd-500/5">
        <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-rasd-600 text-white">
          <Check className="size-3.5" aria-hidden />
        </span>
        <div>
          <p className="mb-1 text-xs font-semibold text-rasd-700 dark:text-rasd-300">{t.site.afterLabel}</p>
          <div className="text-sm font-medium leading-relaxed">{after}</div>
        </div>
      </div>
    </div>
  );
}

export function CtaBand({ title, body, href, label }: { title: string; body: string; href: string; label: string }) {
  const { t } = useI18n();
  return (
    <section className="px-4 pb-20 md:px-6 md:pb-28">
      <div className="relative mx-auto max-w-6xl overflow-hidden rounded-[2rem] bg-ink-900 px-6 py-16 text-center text-paper md:px-12 md:py-24">
        <RadarBackdrop onDark className="-bottom-[34rem] left-1/2 size-[56rem] -translate-x-1/2" />
        <div className="relative mx-auto max-w-2xl">
          <h2 className="text-3xl font-bold tracking-tight text-balance md:text-5xl">{title}</h2>
          <p className="mt-4 text-mist-300 md:text-lg">{body}</p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Button asChild variant="accent" size="xl">
              <Link href={href}>
                {label} <ForwardArrow />
              </Link>
            </Button>
            <Button asChild variant="ghost" size="xl" className="text-paper hover:bg-white/10 hover:text-paper">
              <Link href="/contact">{t.site.contact.interests.demo}</Link>
            </Button>
          </div>
          <TrialNote className="mt-5 text-sm text-mist-300" />
        </div>
      </div>
    </section>
  );
}

export function Faq({ title, items }: { title: string; items: { q: string; a: string }[] }) {
  return (
    <Section>
      <div className="grid gap-10 md:grid-cols-[1fr_2fr]">
        <Reveal>
          <h2 className="text-3xl font-bold tracking-tight md:text-4xl">{title}</h2>
        </Reveal>
        <div className="divide-y rounded-2xl border bg-card">
          {items.map((f) => (
            <details key={f.q} className="group p-5 md:p-6">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                {f.q}
                <ChevronDown className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden />
              </summary>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{f.a}</p>
            </details>
          ))}
        </div>
      </div>
    </Section>
  );
}
