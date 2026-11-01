"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownRight,
  ArrowUpRight,
  BadgeCheck,
  BarChart3,
  Check,
  ChevronDown,
  Coins,
  MessageCircle,
  Phone,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { DemoBadge, PriorityBadge, ScorePill, StatusBadge } from "@/components/badges";
import { HBarChart, ScoreHistogram, TrendChart } from "@/components/charts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, Progress } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { OutOfCredits } from "@/features/billing/out-of-credits";
import { RadarBackdrop } from "@/features/site/motion";
import { whatsappUrl } from "@/features/leads/links";
import { useDashboard, useMe, useMeta, useProfile } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn, formatMoney, formatNumber, relativeTime } from "@/lib/utils";
import type { DashboardStats } from "@/types/api";

import { ReviewPrompt } from "./review";

const PIPELINE = ["new", "qualified", "contacted", "replied", "meeting_scheduled", "won"] as const;

const CHECKLIST_LINKS: Record<keyof DashboardStats["checklist"], string> = {
  email_verified: "/app/settings",
  profile: "/app/settings?tab=business",
  telegram: "/app/settings?tab=telegram",
  campaign: "/app/campaigns/new",
  contacted: "/app/leads",
};

function Kpi({
  label,
  value,
  icon: Icon,
  current,
  previous,
  accent,
}: {
  label: string;
  value: number;
  icon: React.ComponentType<{ className?: string }>;
  current: number;
  previous: number;
  accent?: boolean;
}) {
  const { t, locale } = useI18n();
  const change = previous > 0 ? Math.round(((current - previous) / previous) * 100) : null;
  const up = (change ?? 0) >= 0;
  return (
    <Card className={cn("relative overflow-hidden", accent && "border-ink-900 bg-ink-900 text-paper dark:border-rasd-500/30")}>
      <CardContent className="p-4 md:p-5">
        <div className="flex items-start justify-between gap-2">
          <p className={cn("text-xs md:text-sm", accent ? "text-mist-300" : "text-muted-foreground")}>{label}</p>
          <span className={cn("hidden rounded-lg p-2 sm:inline-flex", accent ? "bg-white/10 text-signal-400" : "bg-rasd-50 text-rasd-700 dark:bg-rasd-500/10 dark:text-rasd-300")}>
            <Icon className="size-4" />
          </span>
        </div>
        <p className="mt-2 font-display text-2xl font-bold tabular-nums tracking-tight md:mt-3 md:text-3xl">{formatNumber(value, locale)}</p>
        <p className={cn("mt-1 flex items-center gap-1 text-xs", accent ? "text-mist-300" : "text-muted-foreground")}>
          {change === null ? (
            t.overview.noPrev
          ) : (
            <>
              {up ? (
                <ArrowUpRight className={cn("size-3.5", accent ? "text-signal-400" : "text-success")} aria-hidden />
              ) : (
                <ArrowDownRight className="size-3.5 text-destructive" aria-hidden />
              )}
              {t.overview.vsPrev.replace("{n}", `${up ? "+" : ""}${change}`)}
            </>
          )}
        </p>
      </CardContent>
    </Card>
  );
}

function Checklist({ items }: { items: DashboardStats["checklist"] }) {
  const { t } = useI18n();
  const keys = Object.keys(CHECKLIST_LINKS) as (keyof DashboardStats["checklist"])[];
  const done = keys.filter((k) => items[k]).length;
  if (done === keys.length) return null;
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>{t.overview.checklistTitle}</CardTitle>
        <span className="text-xs text-muted-foreground">
          {t.overview.checklistProgress.replace("{done}", String(done)).replace("{total}", String(keys.length))}
        </span>
      </CardHeader>
      <CardContent className="space-y-3">
        <Progress value={(done / keys.length) * 100} label={t.overview.checklistTitle} />
        <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {keys.map((k, i) => (
            <li key={k}>
              <Link
                href={CHECKLIST_LINKS[k]}
                className={cn(
                  "flex h-full items-center gap-2.5 rounded-xl border p-3 text-sm transition-colors",
                  items[k] ? "border-transparent bg-muted/60 text-muted-foreground line-through" : "hover:border-rasd-500/50 hover:bg-rasd-50/50 dark:hover:bg-rasd-500/5",
                )}
              >
                <span
                  className={cn(
                    "flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                    items[k] ? "bg-rasd-600 text-white" : "border",
                  )}
                >
                  {items[k] ? <Check className="size-3.5" /> : i + 1}
                </span>
                {t.overview.checklist[k]}
              </Link>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function NextActions({ items }: { items: DashboardStats["next_actions"] }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const mark = useMutation({
    mutationFn: (id: string) => api(`/leads/${id}`, { method: "PATCH", body: { crm_status: "contacted" } }),
    onSuccess: () => {
      toast.success(t.overview.marked);
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });
  return (
    <Card className="lg:col-span-2">
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>{t.overview.nextTitle}</CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">{t.overview.nextSubtitle}</p>
        </div>
        <Button asChild variant="ghost" size="sm">
          <Link href="/app/leads">{t.overview.viewAll}</Link>
        </Button>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">{t.overview.nextEmpty}</p>
        ) : (
          <ul className="divide-y">
            {items.map((l) => {
              const wa = l.whatsapp ? whatsappUrl(l.whatsapp, l.whatsapp_message) : null;
              return (
                <li key={l.id} className="flex flex-wrap items-center gap-3 py-3">
                  <ScorePill score={l.score} />
                  <Link href={`/app/leads/${l.id}`} className="min-w-0 flex-1 hover:underline">
                    <p className="truncate font-medium">{l.name}</p>
                    <p className="truncate text-xs text-muted-foreground">{[l.city, l.country].filter(Boolean).join(", ")}</p>
                  </Link>
                  <div className="flex items-center gap-1.5">
                    {wa ? (
                      <Button asChild size="sm" className="bg-[#25d366] text-white hover:bg-[#1ebe5b]">
                        <a href={wa} target="_blank" rel="noopener noreferrer">
                          <MessageCircle /> {t.overview.whatsapp}
                        </a>
                      </Button>
                    ) : l.phone ? (
                      <Button asChild size="sm" variant="outline">
                        <a href={`tel:${l.phone.replace(/[^\d+]/g, "")}`}>
                          <Phone /> {t.overview.call}
                        </a>
                      </Button>
                    ) : null}
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={mark.isPending}
                      onClick={() => mark.mutate(l.id)}
                      title={t.overview.markContacted}
                      aria-label={`${t.overview.markContacted}: ${l.name}`}
                    >
                      <Check />
                      <span className="hidden sm:inline">{t.overview.markContacted}</span>
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function Pipeline({ counts }: { counts: Record<string, number> }) {
  const { t, locale } = useI18n();
  const max = Math.max(1, ...PIPELINE.map((k) => counts[k] ?? 0));
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.overview.pipelineTitle}</CardTitle>
        <p className="text-sm text-muted-foreground">{t.overview.pipelineSubtitle}</p>
      </CardHeader>
      <CardContent>
        <ul className="space-y-3">
          {PIPELINE.map((k) => {
            const n = counts[k] ?? 0;
            return (
              <li key={k}>
                <Link href={`/app/leads?crm_status=${k}`} className="group block">
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className="group-hover:underline">{t.crm[k]}</span>
                    <span className="font-medium tabular-nums">{formatNumber(n, locale)}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className={cn("h-full rounded-full", k === "won" ? "bg-signal-500" : "bg-rasd-600")}
                      style={{ width: `${(n / max) * 100}%` }}
                    />
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

/** Full radar hero until the first leads arrive; afterwards a slim header so daily work starts above the fold. */
function Welcome({ compact }: { compact: boolean }) {
  const { t } = useI18n();
  const { data: me } = useMe();
  const name = (me?.user.full_name || me?.user.email || "").split(" ")[0];
  if (compact) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-xl font-bold tracking-tight md:text-2xl">{t.overview.greeting.replace("{name}", name)}</h1>
          <p className="text-sm text-muted-foreground">{t.overview.greetingSub}</p>
        </div>
        <Button asChild variant="accent" className="hidden md:inline-flex">
          <Link href="/app/campaigns/new">
            <Sparkles /> {t.nav.newCampaign}
          </Link>
        </Button>
      </div>
    );
  }
  return (
    <div className="relative overflow-hidden rounded-2xl bg-ink-900 p-6 text-paper md:p-8">
      <RadarBackdrop onDark className="-top-40 end-[-10rem] size-[30rem]" />
      <div className="relative flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight md:text-3xl">{t.overview.greetingNew.replace("{name}", name)}</h1>
          <p className="mt-1 text-mist-300">{t.overview.greetingNewSub}</p>
        </div>
        <Button asChild variant="accent" size="lg">
          <Link href="/app/campaigns/new">
            <Sparkles /> {t.nav.newCampaign}
          </Link>
        </Button>
      </div>
    </div>
  );
}

function ActiveSearches({ items }: { items: DashboardStats["active_campaigns"] }) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.overview.activeList}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.length === 0 ? (
          <div className="space-y-3 rounded-xl border border-dashed p-5 text-center">
            <p className="text-sm text-muted-foreground">{t.common.empty}</p>
            <Button asChild size="sm" variant="outline">
              <Link href="/app/campaigns/new">
                <Sparkles /> {t.nav.newCampaign}
              </Link>
            </Button>
          </div>
        ) : (
          items.map((c) => (
            <Link key={c.id} href={`/app/campaigns/${c.id}`} className="block space-y-2 rounded-lg p-2 hover:bg-muted">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium">{c.name}</span>
                <span className="flex items-center gap-1.5">
                  {c.is_demo ? <DemoBadge /> : null}
                  <StatusBadge status={c.status} />
                </span>
              </div>
              <Progress value={c.stats?.progress?.percent ?? null} label={c.name} />
            </Link>
          ))
        )}
      </CardContent>
    </Card>
  );
}

function RecentLeads({ items }: { items: DashboardStats["recent_leads"] }) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.overview.recentLeads}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t.common.empty}</p>
        ) : (
          items.map((l) => (
            <Link key={l.id} href={`/app/leads/${l.id}`} className="flex items-center gap-3 rounded-lg p-2 hover:bg-muted">
              <ScorePill score={l.score} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{l.name}</p>
                <p className="text-xs text-muted-foreground">{[l.city, l.country].filter(Boolean).join(", ")}</p>
              </div>
              <PriorityBadge priority={l.priority} />
            </Link>
          ))
        )}
      </CardContent>
    </Card>
  );
}

function RecentActivity({ items }: { items: DashboardStats["recent_activity"] }) {
  const { t, locale, eventText } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.overview.recentActivity}</CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t.common.empty}</p>
        ) : (
          <ol className="space-y-3">
            {items.map((e) => (
              <li key={e.id} className="flex gap-2 text-xs">
                <span
                  className={cn(
                    "mt-1 size-2 shrink-0 rounded-full",
                    e.level === "error" ? "bg-destructive" : e.level === "warning" ? "bg-sun-500" : "bg-rasd-500",
                  )}
                  aria-hidden
                />
                <div className="min-w-0">
                  <p className="text-foreground">{eventText(e.data, e.message)}</p>
                  <p className="text-muted-foreground">
                    <Link href={`/app/campaigns/${e.campaign_id}`} className="hover:underline">
                      {e.campaign}
                    </Link>{" "}
                    · {relativeTime(e.created_at, locale)}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

const ANALYTICS_KEY = "rasd-dashboard-analytics";

/** Charts are for the weekly look back, not the daily routine: collapsed by default, the choice is remembered. */
function Analytics({ data }: { data: DashboardStats }) {
  const { t, locale } = useI18n();
  const { data: meta } = useMeta();
  const [open, setOpen] = useState(() => {
    try {
      return typeof window !== "undefined" && window.localStorage.getItem(ANALYTICS_KEY) === "1";
    } catch {
      return false;
    }
  });
  const toggle = () => {
    setOpen((v) => {
      try {
        window.localStorage.setItem(ANALYTICS_KEY, v ? "0" : "1");
      } catch {
        /* storage unavailable: keep the choice for this visit only */
      }
      return !v;
    });
  };
  const industryName = (k: string) => {
    const i = meta?.industries.find((x) => x.key === k);
    return i ? (locale === "ar" ? i.ar : i.en) : k;
  };
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-display text-lg font-semibold">
          <BarChart3 className="size-5 text-rasd-600 dark:text-rasd-300" aria-hidden /> {t.overview.analytics}
        </h2>
        <Button variant="ghost" size="sm" onClick={toggle} aria-expanded={open} aria-controls="dashboard-analytics">
          {open ? t.overview.hideAnalytics : t.overview.showAnalytics}
          <ChevronDown className={cn("transition-transform", open && "rotate-180")} />
        </Button>
      </div>
      {open ? (
        <div id="dashboard-analytics" className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>{t.overview.trend}</CardTitle>
              </CardHeader>
              <CardContent>
                <TrendChart data={data.trend} label={t.overview.trend} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>{t.overview.scoreDistribution}</CardTitle>
              </CardHeader>
              <CardContent>
                <ScoreHistogram data={data.score_distribution} label={t.overview.scoreDistribution} />
              </CardContent>
            </Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>{t.overview.byIndustry}</CardTitle>
              </CardHeader>
              <CardContent>
                <HBarChart data={data.by_industry} label={t.overview.byIndustry} format={industryName} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>{t.overview.byCountry}</CardTitle>
              </CardHeader>
              <CardContent>
                <HBarChart
                  data={data.by_country}
                  label={t.overview.byCountry}
                  format={(k) => {
                    const c = meta?.countries.find((x) => x.code === k);
                    return c ? (locale === "ar" ? c.name_ar : c.name_en) : k;
                  }}
                />
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Ordered by "what do I do today?": header, one alert, setup checklist, the clients to contact now, the searches
 * running, then the numbers and pipeline; charts and the activity log last.
 */
export function Overview() {
  const { t } = useI18n();
  const router = useRouter();
  const { data, isLoading, error, refetch } = useDashboard();
  const { data: me } = useMe();
  const { data: profile } = useProfile();
  // A brand-new workspace goes through onboarding first (admins only: they are the ones who can fill the profile).
  const needsOnboarding =
    !!data &&
    !!profile &&
    !profile.onboarding.completed &&
    data.totals.businesses === 0 &&
    data.active_campaigns.length === 0 &&
    (me?.role === "owner" || me?.role === "admin");
  useEffect(() => {
    if (needsOnboarding) router.replace("/app/welcome");
  }, [needsOnboarding, router]);

  if (isLoading || needsOnboarding) return <LoadingState rows={8} />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;
  const s = data.totals;
  const p = data.period;
  const empty = s.businesses === 0;

  return (
    <div className="space-y-6">
      <Welcome compact={!empty} />
      <OutOfCredits warnLow />
      <Checklist items={data.checklist} />

      {empty ? (
        <>
          {data.active_campaigns.length ? <ActiveSearches items={data.active_campaigns} /> : null}
          <Card className="relative overflow-hidden">
            <CardContent className="flex flex-col items-center gap-4 p-10 text-center">
              <span className="flex size-14 items-center justify-center rounded-2xl bg-ink-900 text-signal-400">
                <Sparkles className="size-7" />
              </span>
              <p className="font-display text-xl font-semibold">{t.overview.emptyTitle}</p>
              <p className="max-w-md text-sm text-muted-foreground">{t.overview.emptyBody}</p>
              <Button asChild variant="ink" size="lg">
                <Link href="/app/campaigns/new">{t.nav.newCampaign}</Link>
              </Button>
            </CardContent>
          </Card>
        </>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            <NextActions items={data.next_actions} />
            <ActiveSearches items={data.active_campaigns} />
          </div>

          <div>
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <Kpi label={t.overview.newLeads} value={p.new.current} current={p.new.current} previous={p.new.previous} icon={Users} accent />
              <Kpi label={t.overview.reachable} value={p.with_contact.current} current={p.with_contact.current} previous={p.with_contact.previous} icon={BadgeCheck} />
              <Kpi label={t.overview.qualified} value={p.qualified.current} current={p.qualified.current} previous={p.qualified.previous} icon={Target} />
              <Kpi label={t.overview.creditsUsed} value={p.credits_used.current} current={p.credits_used.current} previous={p.credits_used.previous} icon={Coins} />
            </div>
            <p className="mt-2 text-xs text-muted-foreground">{t.overview.last30}</p>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Pipeline counts={data.pipeline} />
            <RecentLeads items={data.recent_leads} />
            <RecentActivity items={data.recent_activity} />
          </div>

          {data.checklist.campaign ? <ReviewPrompt /> : null}
          <Analytics data={data} />
        </>
      )}

      {s.ai_cost_usd !== undefined ? (
        <p className="text-xs text-muted-foreground">
          {t.overview.aiCost}: {formatMoney(s.ai_cost_usd)} · {t.overview.discoveryCost}: {formatMoney(s.discovery_cost_usd ?? 0)}
        </p>
      ) : null}
    </div>
  );
}
