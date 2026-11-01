"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Building2,
  Check,
  Clock,
  Gauge,
  Globe2,
  Languages,
  ListX,
  MessageCircle,
  MessageSquareText,
  MessagesSquare,
  Radar,
  Send,
  Sparkles,
  Target,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn, formatNumber } from "@/lib/utils";
import type { CreditPackage } from "@/types/api";

import { CostCalculator } from "./cost-calculator";
import { LivePreview } from "./live-preview";
import { DecisionMakerMockup, HeroMockup, LeadsTableMockup, MessageMockup, ScoreBadge, WhyCardMockup } from "./mockups";
import { Ping, RadarBackdrop, Reveal } from "./motion";
import { BeforeAfter, CtaBand, Eyebrow, Faq, ForwardArrow, Heading, Section, TrialNote } from "./parts";
import { Testimonials } from "./testimonials";
import { UseCaseTabs } from "./use-cases";

const PROBLEM_ICONS = [Clock, ListX, MessagesSquare];
const STEP_ICONS = [Target, Radar, Send];
const FEATURE_ICONS = [Sparkles, MessageCircle, Target, Gauge, MessageSquareText, Building2];
const WHY_ICONS = [Languages, Globe2, Wallet, MessageCircle];

function Hero() {
  const { t } = useI18n();
  const h = t.site.home;
  return (
    <section className="relative overflow-hidden px-4 pb-16 pt-12 md:px-6 md:pb-24 md:pt-20">
      <div
        aria-hidden
        className="bg-grid pointer-events-none absolute inset-0 text-ink-900 [mask-image:radial-gradient(ellipse_at_top,black,transparent_75%)] dark:text-paper"
      />
      <RadarBackdrop className="-top-[24rem] end-[-22rem] size-[60rem]" />
      <div className="relative mx-auto grid max-w-6xl items-center gap-14 lg:grid-cols-[1.05fr_1fr]">
        <div>
          <Eyebrow>{h.eyebrow}</Eyebrow>
          <h1 className="mt-6 text-4xl font-bold leading-[1.15] tracking-tight text-balance md:text-6xl md:leading-[1.1]">
            {h.title}{" "}
            <span className="relative isolate text-rasd-700 dark:text-rasd-300">
              {h.titleHighlight}
              <span aria-hidden className="absolute inset-x-0 bottom-1 -z-10 h-3 rounded-full bg-signal-400/60 md:h-4" />
            </span>
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground text-pretty">{h.subtitle}</p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Button asChild variant="ink" size="xl">
              <Link href="/register">
                {h.ctaPrimary} <ForwardArrow />
              </Link>
            </Button>
            <Button asChild variant="outline" size="xl">
              <Link href="/how-it-works">{h.ctaSecondary}</Link>
            </Button>
          </div>
          <TrialNote className="mt-4 text-sm text-muted-foreground" />
        </div>
        <HeroMockup />
      </div>
    </section>
  );
}

function ProofBar() {
  const { t } = useI18n();
  return (
    <section className="border-y bg-card px-4 md:px-6">
      <dl className="mx-auto grid max-w-6xl grid-cols-2 md:grid-cols-4">
        {t.site.home.proof.map((p, i) => (
          <div key={p.label} className={cn("px-2 py-7 md:px-6", i > 0 && "md:border-s")}>
            <dt className="font-display text-3xl font-bold tracking-tight text-rasd-700 dark:text-rasd-300">{p.value}</dt>
            <dd className="mt-1 text-sm text-muted-foreground">{p.label}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Problems() {
  const { t } = useI18n();
  const h = t.site.home;
  return (
    <Section>
      <Heading title={h.problemTitle} subtitle={h.problemSubtitle} />
      <div className="grid gap-4 md:grid-cols-3">
        {h.problems.map((p, i) => {
          const Icon = PROBLEM_ICONS[i] ?? Clock;
          return (
            <Reveal key={p.title} delay={i * 80} className="flex flex-col rounded-2xl border bg-card p-7">
              <span className="flex size-11 items-center justify-center rounded-xl bg-rose-500/10 text-rose-600 dark:text-rose-300">
                <Icon className="size-5" aria-hidden />
              </span>
              <h3 className="mt-5 text-lg font-semibold">{p.title}</h3>
              <p className="mt-2 flex-1 leading-relaxed text-muted-foreground">{p.body}</p>
              <p className="mt-5 flex gap-2.5 rounded-xl bg-rasd-50 p-3.5 text-sm leading-relaxed dark:bg-rasd-500/10">
                <Check className="mt-0.5 size-4 shrink-0 text-rasd-600 dark:text-rasd-300" aria-hidden />
                <span>
                  <span className="font-semibold text-rasd-800 dark:text-rasd-200">{t.site.afterLabel}: </span>
                  {p.fix}
                </span>
              </p>
            </Reveal>
          );
        })}
      </div>
    </Section>
  );
}

function StepVisual({ i }: { i: number }) {
  const { t } = useI18n();
  if (i === 0) {
    const ex = t.site.home.tryExamples[0];
    return (
      <div className="space-y-2 rounded-xl bg-muted/60 p-4 text-sm">
        <p className="rounded-lg border bg-card px-3 py-2">{ex.label}</p>
        <div className="flex flex-wrap gap-1.5">
          {ex.segments.map((s) => (
            <span
              key={s.name}
              className="rounded-full bg-rasd-100 px-2.5 py-1 text-xs text-rasd-800 dark:bg-rasd-500/15 dark:text-rasd-200"
            >
              {s.name}
            </span>
          ))}
        </div>
      </div>
    );
  }
  if (i === 1) {
    return (
      <div className="relative flex h-[7.5rem] items-center justify-center overflow-hidden rounded-xl bg-ink-900">
        <RadarBackdrop onDark className="size-56" />
        <Ping className="absolute start-[62%] top-[30%]" />
        <Ping className="absolute start-[30%] top-[58%]" />
        <Ping className="absolute start-[55%] top-[70%]" />
      </div>
    );
  }
  const row = t.site.mockup.rows[0];
  return (
    <div className="flex items-center gap-3 rounded-xl bg-ink-900 p-4 text-paper">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{row.name}</p>
        <p className="truncate text-xs text-mist-300">{t.site.mockup.why[0]}</p>
      </div>
      <ScoreBadge score={92} />
    </div>
  );
}

function Steps() {
  const { t } = useI18n();
  const h = t.site.home;
  return (
    <Section id="how" tone="muted">
      <Heading title={h.stepsTitle} subtitle={h.stepsSubtitle} />
      <ol className="grid gap-4 md:grid-cols-3">
        {h.steps.map((s, i) => {
          const Icon = STEP_ICONS[i] ?? Target;
          return (
            <Reveal as="li" key={s.title} delay={i * 100} className="flex flex-col rounded-2xl border bg-card p-6">
              <div className="flex items-center gap-3">
                <span className="flex size-9 items-center justify-center rounded-full bg-ink-900 font-display text-sm font-bold text-signal-400">
                  {i + 1}
                </span>
                <Icon className="size-5 text-rasd-600" aria-hidden />
              </div>
              <h3 className="mt-5 text-lg font-semibold">{s.title}</h3>
              <p className="mt-2 flex-1 leading-relaxed text-muted-foreground">{s.body}</p>
              <div className="mt-6">
                <StepVisual i={i} />
              </div>
            </Reveal>
          );
        })}
      </ol>
    </Section>
  );
}

/** We bring the person who decides, not only the front-desk number. */
function DecisionMaker() {
  const { t } = useI18n();
  const d = t.site.home.dm;
  return (
    // The mockup's backdrop bleeds past the edge on phones; clip it so the page doesn't scroll sideways.
    <Section className="overflow-x-clip">
      <div className="grid items-center gap-12 lg:grid-cols-2">
        <Reveal>
          <Eyebrow>{d.eyebrow}</Eyebrow>
          <h2 className="mt-4 text-3xl font-bold leading-tight tracking-tight text-balance md:text-[2.75rem]">{d.title}</h2>
          <p className="mt-4 text-lg leading-relaxed text-muted-foreground">{d.subtitle}</p>
          <ul className="mt-6 space-y-3">
            {d.points.map((p) => (
              <li key={p} className="flex gap-3">
                <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-rasd-600 text-white">
                  <Check className="size-3.5" aria-hidden />
                </span>
                <span className="font-medium">{p}</span>
              </li>
            ))}
          </ul>
          <p className="mt-6 text-sm text-muted-foreground">{d.note}</p>
        </Reveal>
        <Reveal delay={120} className="relative mx-auto w-full max-w-md">
          <div className="absolute -inset-6 -z-10 rounded-[2rem] bg-ink-900" aria-hidden />
          <RadarBackdrop onDark className="-top-24 end-[-6rem] -z-10 size-[26rem]" />
          <DecisionMakerMockup />
        </Reveal>
      </div>
    </Section>
  );
}

/** Static "what would Rasd find for me?" demo: illustrative examples, no AI call on the public page. */
function TryIt() {
  const { t } = useI18n();
  const h = t.site.home;
  const [active, setActive] = useState(h.tryExamples[0].key);
  const ex = h.tryExamples.find((x) => x.key === active) ?? h.tryExamples[0];
  return (
    <Section tone="ink">
      <RadarBackdrop onDark className="-top-80 start-[-20rem] size-[48rem]" />
      <Heading title={h.tryTitle} subtitle={h.trySubtitle} onDark />
      <div className="mx-auto max-w-5xl">
        <div className="flex flex-wrap items-center justify-center gap-2" role="group" aria-label={h.tryLabel}>
          <span className="me-1 text-sm text-mist-300">{h.tryLabel}</span>
          {h.tryExamples.map((x) => (
            <button
              key={x.key}
              type="button"
              onClick={() => setActive(x.key)}
              aria-pressed={x.key === active}
              className={cn(
                "rounded-full border px-4 py-2 text-sm font-medium transition-colors",
                x.key === active
                  ? "border-signal-400 bg-signal-400 text-ink-900"
                  : "border-white/15 text-paper hover:border-white/30 hover:bg-white/5",
              )}
            >
              {x.label}
            </button>
          ))}
        </div>
        <div key={ex.key} className="mt-10 grid gap-4 md:grid-cols-[1.4fr_1fr]">
          <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-6">
            <p className="text-xs font-semibold text-mist-300">{h.trySegments}</p>
            <ul className="mt-4 space-y-3">
              {ex.segments.map((s) => (
                <li key={s.name} className="rounded-xl border border-white/10 bg-ink-800/60 p-4">
                  <p className="flex items-center gap-2 font-semibold">
                    <Ping className="size-2" /> {s.name}
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-mist-300">{s.why}</p>
                </li>
              ))}
            </ul>
          </div>
          <div className="flex flex-col rounded-2xl border border-white/10 bg-white/[0.04] p-6">
            <p className="text-xs font-semibold text-mist-300">
              {h.trySample} · {t.site.example}
            </p>
            <div className="mt-4 flex-1 rounded-xl bg-paper p-5 text-ink-900">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-display text-lg font-semibold">{ex.sample.name}</p>
                  <p className="text-sm text-mist-500">{ex.sample.city}</p>
                </div>
                <ScoreBadge score={ex.sample.score} />
              </div>
              <p className="mt-4 text-xs font-semibold text-rasd-700">{t.site.mockup.whyTitle}</p>
              <p className="mt-1 text-sm leading-relaxed">{ex.sample.reason}</p>
            </div>
            <Button asChild variant="accent" className="mt-4">
              <Link href="/register">
                {t.site.nav.startTrial} <ForwardArrow />
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </Section>
  );
}

function BeforeAfterSection() {
  const { t } = useI18n();
  const h = t.site.home;
  return (
    <Section>
      <Heading title={h.beforeAfterTitle} subtitle={h.beforeAfterSubtitle} />
      <div className="mx-auto max-w-4xl space-y-3">
        {h.pairs.map((p, i) => (
          <Reveal key={p.before} delay={i * 60}>
            <BeforeAfter before={p.before} after={p.after} />
          </Reveal>
        ))}
      </div>
    </Section>
  );
}

function Features() {
  const { t } = useI18n();
  const h = t.site.home;
  const card = "rounded-2xl border bg-card p-6";
  const head = (i: number) => {
    const Icon = FEATURE_ICONS[i] ?? Sparkles;
    const f = h.features[i];
    return (
      <>
        <span className="flex size-10 items-center justify-center rounded-xl bg-rasd-50 text-rasd-700 dark:bg-rasd-500/10 dark:text-rasd-300">
          <Icon className="size-5" aria-hidden />
        </span>
        <h3 className="mt-4 text-lg font-semibold">{f.title}</h3>
        <p className="mt-2 leading-relaxed text-muted-foreground">{f.body}</p>
      </>
    );
  };
  return (
    <Section tone="muted">
      <Heading title={h.featuresTitle} subtitle={h.featuresSubtitle} />
      <div className="grid gap-4 md:grid-cols-6">
        <Reveal className={cn(card, "overflow-hidden md:col-span-4")}>
          <div className="grid items-center gap-6 lg:grid-cols-[1fr_1.3fr]">
            <div>{head(0)}</div>
            <LeadsTableMockup className="shadow-none" />
          </div>
        </Reveal>
        <Reveal className={cn(card, "md:col-span-2")} delay={80}>
          {head(1)}
        </Reveal>
        <Reveal className={cn(card, "md:col-span-3")} delay={40}>
          {head(2)}
          <WhyCardMockup className="mt-6 shadow-none" />
        </Reveal>
        <Reveal className={cn(card, "md:col-span-3")} delay={120}>
          {head(4)}
          <MessageMockup className="mt-6 shadow-none" />
        </Reveal>
        <Reveal className={cn(card, "md:col-span-3")} delay={40}>
          {head(3)}
        </Reveal>
        <Reveal className={cn(card, "md:col-span-3")} delay={120}>
          {head(5)}
        </Reveal>
        {/* What sets Rasd apart, folded in here so the page doesn't repeat itself in a separate section. */}
        <div className="grid gap-4 sm:grid-cols-2 md:col-span-6 lg:grid-cols-4">
          {h.why.map((w, i) => {
            const Icon = WHY_ICONS[i] ?? Sparkles;
            return (
              <Reveal key={w.title} delay={i * 60} className="rounded-2xl bg-ink-900 p-6 text-paper">
                <Icon className="size-6 text-signal-400" aria-hidden />
                <h3 className="mt-4 font-semibold">{w.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-mist-300">{w.body}</p>
              </Reveal>
            );
          })}
        </div>
      </div>
    </Section>
  );
}

function UseCasesTeaser() {
  const { t } = useI18n();
  const h = t.site.home;
  return (
    <Section>
      <Heading title={h.useCasesTitle} subtitle={h.useCasesSubtitle} />
      <UseCaseTabs limit={4} />
      <div className="mt-8 text-center">
        <Button asChild variant="outline">
          <Link href="/use-cases">
            {h.useCasesCta} <ForwardArrow />
          </Link>
        </Button>
      </div>
    </Section>
  );
}

function PricingTeaser() {
  const { t, locale } = useI18n();
  const h = t.site.home;
  const pkgs = useQuery({ queryKey: ["public-packages"], queryFn: () => api<CreditPackage[]>("/public/packages"), staleTime: 0 });
  const cheapest = [...(pkgs.data ?? [])].sort((a, b) => Number(a.price) - Number(b.price))[0];
  return (
    <Section>
      <Reveal className="relative mx-auto grid max-w-5xl items-center gap-8 overflow-hidden rounded-[2rem] border bg-card p-8 md:grid-cols-[1.4fr_1fr] md:p-12">
        <div>
          <h2 className="text-3xl font-bold tracking-tight md:text-4xl">{h.pricingTitle}</h2>
          <p className="mt-4 leading-relaxed text-muted-foreground">{h.pricingBody}</p>
        </div>
        <div className="rounded-2xl bg-rasd-50 p-6 text-center dark:bg-rasd-500/10">
          <TrialNote className="font-display text-lg font-semibold text-rasd-800 dark:text-rasd-200" />
          {cheapest ? (
            <p className="mt-2 text-sm text-muted-foreground">
              {h.pricingFrom.replace("{price}", `${formatNumber(Number(cheapest.price), locale)} ${cheapest.currency}`)}
            </p>
          ) : null}
          <div className="mt-5 flex flex-col gap-2">
            <Button asChild variant="ink">
              <Link href="/register">{t.site.nav.startTrial}</Link>
            </Button>
            <Button asChild variant="ghost">
              <Link href="/pricing">{h.pricingCta}</Link>
            </Button>
          </div>
        </div>
      </Reveal>
    </Section>
  );
}

export function HomePage() {
  const { t } = useI18n();
  const h = t.site.home;
  return (
    <>
      <Hero />
      <ProofBar />
      <LivePreview fallback={<TryIt />} />
      <Problems />
      <Steps />
      <DecisionMaker />
      <CostCalculator />
      <BeforeAfterSection />
      <Features />
      <UseCasesTeaser />
      <Testimonials />
      <PricingTeaser />
      <Faq title={h.faqTitle} items={h.faqs} />
      <CtaBand title={h.finalTitle} body={h.finalBody} href="/register" label={t.site.nav.startTrial} />
    </>
  );
}
