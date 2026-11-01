"use client";

import { Briefcase, Calculator, Code2, Megaphone, PackageSearch, PenTool, Wrench } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { useI18n } from "@/i18n/provider";
import { cn } from "@/lib/utils";

import { LivePreview } from "./live-preview";
import { DecisionMakerMockup, MessageMockup, WhyCardMockup } from "./mockups";
import { Reveal } from "./motion";
import { BeforeAfter, CtaBand, ForwardArrow, Heading, PageHero, Section } from "./parts";

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  agency: Megaphone,
  software: Code2,
  accounting: Calculator,
  supplier: PackageSearch,
  consulting: Briefcase,
  freelancer: PenTool,
  maintenance: Wrench,
};

/** Each use case's seller category in the backend catalog (PROVIDER_CATEGORIES): preselected at sign-up and
 * used to filter the live preview. */
export const USE_CASE_CATEGORY: Record<string, string> = {
  agency: "marketing_agency",
  software: "software",
  accounting: "accounting_finance",
  supplier: "medical_supplier",
  consulting: "consulting_training",
  freelancer: "design_branding",
  maintenance: "facility_services",
};

type UseCase = ReturnType<typeof useI18n>["t"]["site"]["useCases"]["items"][number];

function UseCaseBody({ item }: { item: UseCase }) {
  const { t } = useI18n();
  const u = t.site.useCases;
  return (
    <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
      <div className="space-y-6">
        <div>
          <p className="text-xs font-semibold text-muted-foreground">{u.findsLabel}</p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {item.finds.map((f) => (
              <li key={f} className="rounded-full border bg-card px-3 py-1.5 text-sm">
                {f}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="text-xs font-semibold text-muted-foreground">{u.signalsLabel}</p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {item.signals.map((s) => (
              <li key={s} className="rounded-full bg-rasd-100 px-3 py-1.5 text-sm text-rasd-800 dark:bg-rasd-500/15 dark:text-rasd-200">
                {s}
              </li>
            ))}
          </ul>
        </div>
        <BeforeAfter before={item.before} after={item.after} />
      </div>
      <MessageMockup text={item.message} className="h-fit shadow-none" />
    </div>
  );
}

/** Tabs per type of business; used on the home page (first few) and in full on /use-cases. */
export function UseCaseTabs({ limit }: { limit?: number }) {
  const { t } = useI18n();
  const items = t.site.useCases.items.slice(0, limit);
  return (
    <Tabs defaultValue={items[0].key} className="rounded-[2rem] border bg-sand-100 p-3 md:p-4 dark:bg-ink-900">
      <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1 bg-transparent p-0">
        {items.map((it) => {
          const Icon = ICONS[it.key] ?? Briefcase;
          return (
            <TabsTrigger
              key={it.key}
              value={it.key}
              className="rounded-full px-4 py-2 text-sm data-[state=active]:bg-ink-900 data-[state=active]:text-paper dark:data-[state=active]:bg-paper dark:data-[state=active]:text-ink-900"
            >
              <Icon className="size-4" aria-hidden /> {it.title}
            </TabsTrigger>
          );
        })}
      </TabsList>
      {items.map((it) => (
        <TabsContent key={it.key} value={it.key} className="mt-3 rounded-[1.5rem] bg-background p-5 md:p-8">
          <p className="mb-6 font-display text-xl font-semibold">{it.short}</p>
          <UseCaseBody item={it} />
          <Button asChild variant="link" className="mt-4 px-0">
            <Link href={`/use-cases/${it.key}`}>
              {t.site.useCases.seeMore} <ForwardArrow />
            </Link>
          </Button>
        </TabsContent>
      ))}
    </Tabs>
  );
}

export function UseCasesPage() {
  const { t } = useI18n();
  const u = t.site.useCases;
  return (
    <>
      <PageHero eyebrow={u.eyebrow} title={u.title} subtitle={u.subtitle} />
      <Section className="pt-0 md:pt-0">
        <div className="space-y-6">
          {u.items.map((it, i) => {
            const Icon = ICONS[it.key] ?? Briefcase;
            return (
              <Reveal key={it.key} as="section" className={cn("rounded-[2rem] border bg-card p-6 md:p-10")}>
                <div className="mb-8 flex items-start gap-4">
                  <span className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-ink-900 text-signal-400">
                    <Icon className="size-6" aria-hidden />
                  </span>
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground tabular-nums">0{i + 1}</p>
                    <h2 className="text-2xl font-bold tracking-tight md:text-3xl">{it.title}</h2>
                    <p className="mt-1 text-muted-foreground">{it.short}</p>
                  </div>
                </div>
                <UseCaseBody item={it} />
                <Button asChild variant="outline" className="mt-6">
                  <Link href={`/use-cases/${it.key}`}>
                    {u.seeMore} <ForwardArrow />
                  </Link>
                </Button>
              </Reveal>
            );
          })}
        </div>
      </Section>
      <CtaBand title={u.ctaTitle} body={u.ctaBody} href="/register" label={t.site.nav.startTrial} />
    </>
  );
}

/** One page per kind of seller: their pain, who Rasd finds for them, real preview results, and sign-up preset. */
export function UseCaseDetailPage({ slug }: { slug: string }) {
  const { t } = useI18n();
  const u = t.site.useCases;
  const item = u.items.find((x) => x.key === slug) ?? u.items[0];
  const category = USE_CASE_CATEGORY[item.key];
  const register = category ? `/register?category=${category}` : "/register";
  const Icon = ICONS[item.key] ?? Briefcase;
  return (
    <>
      <PageHero eyebrow={item.title} title={item.pain} subtitle={item.short} />
      <Section className="pt-0 md:pt-0">
        <div className="-mt-4 mb-10 flex justify-center">
          <Button asChild variant="ink" size="xl">
            <Link href={register}>
              {t.site.nav.startTrial} <ForwardArrow />
            </Link>
          </Button>
        </div>
        <Reveal className="rounded-[2rem] border bg-card p-6 md:p-10">
          <div className="mb-8 flex items-center gap-4">
            <span className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-ink-900 text-signal-400">
              <Icon className="size-6" aria-hidden />
            </span>
            <h2 className="text-2xl font-bold tracking-tight">{item.title}</h2>
          </div>
          <UseCaseBody item={item} />
        </Reveal>
      </Section>
      <LivePreview fallback={null} category={category} />
      <Section tone="muted">
        <div className="grid gap-4 md:grid-cols-2">
          <WhyCardMockup className="shadow-none" />
          <DecisionMakerMockup />
        </div>
      </Section>
      <Section>
        <Heading title={u.otherTitle} />
        <ul className="flex flex-wrap justify-center gap-2">
          {u.items
            .filter((x) => x.key !== item.key)
            .map((x) => {
              const ItemIcon = ICONS[x.key] ?? Briefcase;
              return (
                <li key={x.key}>
                  <Link
                    href={`/use-cases/${x.key}`}
                    className="inline-flex items-center gap-2 rounded-full border bg-card px-4 py-2 text-sm font-medium hover:bg-muted"
                  >
                    <ItemIcon className="size-4" aria-hidden /> {x.title}
                  </Link>
                </li>
              );
            })}
        </ul>
      </Section>
      <CtaBand title={u.detailCtaTitle} body={u.detailCtaBody} href={register} label={t.site.nav.startTrial} />
    </>
  );
}
