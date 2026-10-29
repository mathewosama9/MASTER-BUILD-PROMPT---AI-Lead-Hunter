"use client";

import {
  Activity,
  BadgeCheck,
  Building2,
  CircleDollarSign,
  Gauge,
  Mail,
  Radar,
  Sparkles,
  Target,
  TrendingUp,
  XCircle,
} from "lucide-react";
import Link from "next/link";

import { PriorityBadge, ScorePill, StatusBadge } from "@/components/badges";
import { HBarChart, ScoreHistogram, TrendChart } from "@/components/charts";
import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, Progress } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useDashboard, useMeta } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { formatMoney, formatNumber, relativeTime } from "@/lib/utils";

function Stat({
  label,
  value,
  icon: Icon,
  hint,
  accent,
}: {
  label: string;
  value: string;
  icon: React.ComponentType<{ className?: string }>;
  hint?: string;
  accent?: boolean;
}) {
  return (
    <Card className={accent ? "border-sun-500/40" : undefined}>
      <CardContent className="flex items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="mt-1 text-2xl font-bold tabular-nums tracking-tight">{value}</p>
          {hint ? <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p> : null}
        </div>
        <div className={`rounded-md p-2 ${accent ? "bg-sun-500/15 text-sun-500" : "bg-brand-500/10 text-primary"}`}>
          <Icon className="size-4" />
        </div>
      </CardContent>
    </Card>
  );
}

export function Overview() {
  const { t, locale, label, eventText } = useI18n();
  const { data, isLoading, error, refetch } = useDashboard();
  const { data: meta } = useMeta();
  const industryName = (k: string) => {
    const i = meta?.industries.find((x) => x.key === k);
    return i ? (locale === "ar" ? i.ar : i.en) : label(k);
  };

  if (isLoading) return <LoadingState rows={8} />;
  if (error || !data) return <ErrorState error={error} onRetry={() => refetch()} />;
  const s = data.totals;
  const n = (v: number) => formatNumber(v, locale);

  return (
    <div className="space-y-6">
      <PageHeader
        title={t.overview.title}
        subtitle={t.overview.subtitle}
        actions={
          <Button asChild variant="accent">
            <Link href="/campaigns/new">
              <Sparkles /> {t.nav.newCampaign}
            </Link>
          </Button>
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label={t.overview.totalBusinesses} value={n(s.businesses)} icon={Building2} />
        <Stat label={t.overview.qualified} value={n(s.qualified_leads)} icon={Target} accent />
        <Stat label={t.overview.verifiedContacts} value={n(s.with_verified_contact)} icon={BadgeCheck}
              hint={`${t.overview.withContacts}: ${n(s.with_contact)}`} />
        <Stat label={t.overview.avgScore} value={s.average_score !== null ? String(s.average_score) : "—"} icon={Gauge} />
        <Stat label={t.overview.conversion} value={s.conversion_rate !== null ? `${s.conversion_rate}%` : "—"} icon={TrendingUp} />
        <Stat label={t.overview.activeCampaigns} value={n(s.active_campaigns)} icon={Radar}
              hint={`${t.overview.completedCampaigns}: ${n(s.completed_campaigns)}`} />
        <Stat label={t.overview.failedCampaigns} value={n(s.failed_campaigns)} icon={XCircle} />
        <Stat label={t.overview.today} value={n(s.today)} icon={Activity}
              hint={`${t.overview.week}: ${n(s.week)} · ${t.overview.month}: ${n(s.month)}`} />
        <Stat label={t.overview.aiCost} value={formatMoney(s.ai_cost_usd)} icon={CircleDollarSign} />
        <Stat label={t.overview.discoveryCost} value={formatMoney(s.discovery_cost_usd)} icon={Mail} />
      </div>

      {s.businesses === 0 ? (
        <EmptyState
          title={t.campaigns.noCampaigns}
          action={
            <Button asChild>
              <Link href="/campaigns/new">{t.nav.newCampaign}</Link>
            </Button>
          }
        />
      ) : (
        <>
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
          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>{t.overview.byCountry}</CardTitle>
              </CardHeader>
              <CardContent>
                <HBarChart data={data.by_country} label={t.overview.byCountry} format={(k) => {
                  const c = meta?.countries.find((x) => x.code === k);
                  return c ? (locale === "ar" ? c.name_ar : c.name_en) : k;
                }} />
              </CardContent>
            </Card>
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
                <CardTitle>{t.overview.bySource}</CardTitle>
              </CardHeader>
              <CardContent>
                <HBarChart data={data.by_source} label={t.overview.bySource} format={(k) => label(k)} />
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>{t.overview.activeList}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {data.active_campaigns.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t.common.empty}</p>
            ) : (
              data.active_campaigns.map((c) => (
                <Link key={c.id} href={`/campaigns/${c.id}`} className="block space-y-2 rounded-md p-2 hover:bg-muted">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{c.name}</span>
                    <StatusBadge status={c.status} />
                  </div>
                  <Progress value={c.stats?.progress?.percent ?? null} label={c.name} />
                </Link>
              ))
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t.overview.recentLeads}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {data.recent_leads.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t.common.empty}</p>
            ) : (
              data.recent_leads.map((l) => (
                <Link key={l.id} href={`/leads/${l.id}`} className="flex items-center gap-3 rounded-md p-2 hover:bg-muted">
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
        <Card>
          <CardHeader>
            <CardTitle>{t.overview.recentActivity}</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="space-y-3">
              {data.recent_activity.map((e) => (
                <li key={e.id} className="flex gap-2 text-xs">
                  <span
                    className={`mt-1 size-2 shrink-0 rounded-full ${
                      e.level === "error" ? "bg-destructive" : e.level === "warning" ? "bg-sun-500" : "bg-brand-500"
                    }`}
                    aria-hidden
                  />
                  <div className="min-w-0">
                    <p className="text-foreground">{eventText(e.data, e.message)}</p>
                    <p className="text-muted-foreground">
                      <Link href={`/campaigns/${e.campaign_id}`} className="hover:underline">{e.campaign}</Link> ·{" "}
                      {relativeTime(e.created_at, locale)}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
