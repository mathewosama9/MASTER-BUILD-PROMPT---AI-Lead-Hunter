"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, CheckCircle2, CreditCard, Gift, Landmark, Wallet } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/primitives";
import { PackageCard, popularIndex } from "@/features/billing/package-card";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { CreditPackage } from "@/types/api";

import { CostCalculator } from "./cost-calculator";
import { Reveal } from "./motion";
import { Faq, ForwardArrow, PageHero, Section, useTrialTerms } from "./parts";
import { useSignedIn } from "./site-shell";

function Packages() {
  const { t } = useI18n();
  const p = t.site.pricing;
  // Admin edits show up immediately: no long cache for prices.
  const q = useQuery({ queryKey: ["public-packages"], queryFn: () => api<CreditPackage[]>("/public/packages"), staleTime: 0 });
  const signedIn = useSignedIn();
  if (q.isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-64 rounded-2xl" />
        ))}
      </div>
    );
  }
  if (!q.data?.length) {
    return (
      <div className="rounded-2xl border bg-card p-6 text-center text-sm text-muted-foreground">
        {p.noPackages}{" "}
        <Link href="/contact" className="font-medium text-primary hover:underline">
          {t.site.nav.contact}
        </Link>
      </div>
    );
  }
  const popular = popularIndex(q.data);
  return (
    <div className={cn("grid gap-4 sm:grid-cols-2", q.data.length >= 3 && "lg:grid-cols-3")}>
      {q.data.map((pkg, i) => (
        <PackageCard key={pkg.id} pkg={pkg} hot={i === popular}>
          <Button asChild variant={i === popular ? "accent" : "outline"} className="w-full">
            {/* Signed-in visitors go straight to checkout with this package picked; others sign up first. */}
            <Link href={signedIn ? `/app/billing?pkg=${pkg.id}` : "/register"}>{p.buy}</Link>
          </Button>
        </PackageCard>
      ))}
    </div>
  );
}

export function PricingPage() {
  const { t } = useI18n();
  const p = t.site.pricing;
  const trial = useTrialTerms();
  return (
    <>
      <PageHero eyebrow={p.eyebrow} title={p.title} subtitle={p.subtitle} />

      <Section className="pt-0 md:pt-0">
        <Reveal className="mx-auto flex max-w-4xl flex-col items-start gap-5 rounded-2xl border border-rasd-600/25 bg-rasd-50 p-6 sm:flex-row sm:items-center md:p-8 dark:bg-rasd-500/10">
          <span className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-ink-900 text-signal-400">
            <Gift className="size-7" aria-hidden />
          </span>
          <div className="flex-1">
            <h2 className="text-xl font-bold">{p.trialTitle}</h2>
            <p className="mt-1 text-muted-foreground">
              {trial.data
                ? p.trialBody.replace("{days}", String(trial.data.trial_days)).replace("{credits}", String(trial.data.trial_credits))
                : "…"}
            </p>
          </div>
          <Button asChild variant="ink" size="lg">
            <Link href="/register">
              {p.trialCta} <ForwardArrow />
            </Link>
          </Button>
        </Reveal>

        <div className="mt-20">
          <h2 className="mb-10 text-center text-3xl font-bold tracking-tight">{p.packagesTitle}</h2>
          <Packages />
        </div>

        <div className="mx-auto mt-14 max-w-4xl rounded-2xl border bg-card p-6 md:p-8">
          <h3 className="font-semibold">{p.includedTitle}</h3>
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {p.included.map((x) => (
              <li key={x} className="flex gap-2.5 text-sm">
                <Check className="mt-0.5 size-4 shrink-0 text-rasd-600" aria-hidden /> {x}
              </li>
            ))}
          </ul>
        </div>
      </Section>

      <Section tone="muted">
        <div className="grid gap-10 md:grid-cols-2">
          <div>
            <h2 className="flex items-center gap-2 text-2xl font-bold">
              <Wallet className="size-6 text-rasd-600" aria-hidden /> {p.howTitle}
            </h2>
            <ul className="mt-6 space-y-3">
              {p.how.map((x) => (
                <li key={x} className="flex gap-2.5 leading-relaxed">
                  <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-rasd-600" aria-hidden /> {x}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h2 className="flex items-center gap-2 text-2xl font-bold">
              <Landmark className="size-6 text-rasd-600" aria-hidden /> {p.paymentTitle}
            </h2>
            <p className="mt-6 leading-relaxed text-muted-foreground">{p.paymentBody}</p>
            <div className="mt-5 flex flex-wrap gap-2 text-sm">
              <span className="inline-flex items-center gap-1.5 rounded-full border bg-card px-3 py-1.5">
                <CreditCard className="size-3.5" aria-hidden /> {t.labels.paypal}
              </span>
            </div>
            <Button asChild variant="link" className="mt-4 px-0">
              <Link href="/contact">{p.contactCta}</Link>
            </Button>
          </div>
        </div>
      </Section>

      <CostCalculator tone="plain" />

      <Faq title={t.site.home.faqTitle} items={t.site.home.faqs} />
    </>
  );
}
