"use client";

import { CheckCircle2, Coins } from "lucide-react";

import { useI18n } from "@/i18n/provider";
import { cn } from "@/lib/utils";

import { DecisionMakerMockup, MessageMockup, WhyCardMockup } from "./mockups";
import { Ping, RadarBackdrop, Reveal } from "./motion";
import { CtaBand, PageHero, Section } from "./parts";

function ProfileMockup() {
  const { t } = useI18n();
  const ex = t.site.home.tryExamples[0];
  return (
    <div className="space-y-3 rounded-2xl border bg-card p-5">
      <div className="rounded-xl border bg-muted/50 px-4 py-3 text-sm">{ex.label}</div>
      <div className="flex flex-wrap gap-2">
        {ex.segments.map((s) => (
          <span key={s.name} className="rounded-full bg-rasd-100 px-3 py-1 text-xs text-rasd-800 dark:bg-rasd-500/15 dark:text-rasd-200">
            {s.name}
          </span>
        ))}
      </div>
      <p className="text-sm leading-relaxed text-muted-foreground">{ex.segments[0].why}</p>
    </div>
  );
}

function SearchMockup() {
  return (
    <div className="relative flex aspect-[4/3] items-center justify-center overflow-hidden rounded-2xl bg-ink-900">
      <RadarBackdrop onDark className="size-[130%]" />
      <Ping className="absolute start-[64%] top-[28%]" />
      <Ping className="absolute start-[28%] top-[44%]" />
      <Ping className="absolute start-[52%] top-[66%]" />
      <Ping className="absolute start-[74%] top-[58%]" />
    </div>
  );
}

const VISUALS = [ProfileMockup, SearchMockup, () => <DecisionMakerMockup />, () => <WhyCardMockup />, () => <MessageMockup />];

export function HowItWorksPage() {
  const { t } = useI18n();
  const h = t.site.how;
  return (
    <>
      <PageHero eyebrow={h.eyebrow} title={h.title} subtitle={h.subtitle} />
      <Section className="pt-0 md:pt-0">
        <ol className="relative space-y-16 md:space-y-24">
          {h.stages.map((s, i) => {
            const Visual = VISUALS[i] ?? ProfileMockup;
            return (
              <Reveal as="li" key={s.title} className="grid items-center gap-8 md:grid-cols-2 md:gap-16">
                <div className={cn(i % 2 === 1 && "md:order-2")}>
                  <span className="inline-flex size-10 items-center justify-center rounded-full bg-ink-900 font-display font-bold text-signal-400">
                    {i + 1}
                  </span>
                  <h2 className="mt-5 text-3xl font-bold tracking-tight">{s.title}</h2>
                  <p className="mt-4 text-lg leading-relaxed text-muted-foreground">{s.body}</p>
                  <ul className="mt-6 space-y-2.5">
                    {s.points.map((p) => (
                      <li key={p} className="flex gap-2.5">
                        <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-rasd-600" aria-hidden /> {p}
                      </li>
                    ))}
                  </ul>
                </div>
                <div className={cn("mx-auto w-full max-w-md", i % 2 === 1 && "md:order-1")}>
                  <Visual />
                </div>
              </Reveal>
            );
          })}
        </ol>
      </Section>
      <Section tone="muted">
        <Reveal className="mx-auto max-w-3xl rounded-[2rem] border bg-card p-8 md:p-12">
          <h2 className="flex items-center gap-3 text-2xl font-bold tracking-tight md:text-3xl">
            <Coins className="size-7 text-rasd-600" aria-hidden /> {h.chargeTitle}
          </h2>
          <ul className="mt-6 space-y-3">
            {h.charge.map((c) => (
              <li key={c} className="flex gap-2.5 leading-relaxed">
                <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-rasd-600" aria-hidden /> {c}
              </li>
            ))}
          </ul>
        </Reveal>
      </Section>
      <div className="pt-20 md:pt-28" />
      <CtaBand title={h.ctaTitle} body={h.ctaBody} href="/register" label={t.site.nav.startTrial} />
    </>
  );
}
