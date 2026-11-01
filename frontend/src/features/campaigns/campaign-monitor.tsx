"use client";

import { AlertTriangle, CheckCircle2, CircleDot, Info, Radio, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { DemoBadge, StatusBadge } from "@/components/badges";
import { PageHeader } from "@/components/layout/app-shell";
import { Badge, Card, CardContent, CardHeader, CardTitle, Progress } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { OutOfCredits } from "@/features/billing/out-of-credits";
import { ACTIVE, useCampaignLive, useMeta, usePlatformAdmin } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { formatDate, formatMoney } from "@/lib/utils";

import { LeadsTable } from "../leads/leads-table";
import { CampaignActions } from "./actions";

const STAGES = ["discovery", "normalization", "deduplication", "company_enrichment", "contact_enrichment", "ai_analysis", "lead_scoring", "done"];

function Metric({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function CampaignMonitor({ id }: { id: string }) {
  const { t, locale, label, source, eventText } = useI18n();
  const platformAdmin = usePlatformAdmin();
  const { data: meta } = useMeta();
  const { campaign, events, live, transport } = useCampaignLive(id);
  const logRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [events.length]);

  if (campaign.isLoading) return <LoadingState rows={6} />;
  if (campaign.error || !campaign.data) return <ErrorState error={campaign.error} onRetry={() => campaign.refetch()} />;
  const c = campaign.data;
  const s = c.stats ?? {};
  const running = ACTIVE.includes(c.status);
  const stageIdx = STAGES.indexOf(c.stage === "company_enrichment" ? "company_enrichment" : c.stage);
  const warnings = events.filter((e) => e.level !== "info");
  const ind = meta?.industries.find((x) => x.key === c.industry);
  const industryName = ind ? (locale === "ar" ? ind.ar : ind.en) : label(c.industry);

  return (
    <div className="space-y-6">
      <PageHeader
        title={c.name}
        subtitle={`${c.country}${c.city ? ` · ${c.city}` : ""} · ${industryName} · ${formatDate(c.created_at, locale)}`}
        actions={<CampaignActions c={c} />}
      />
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={c.status} />
        {c.is_demo ? <DemoBadge /> : null}
        <Badge tone="neutral">{t.monitor.origin}: {label(c.origin)}</Badge>
        {s.ai_provider ? <Badge tone={s.ai_provider === "heuristic" ? "yellow" : "indigo"}>{t.monitor.analysis}: {source(s.ai_provider)}</Badge> : null}
        {running ? (
          <Badge tone="blue">
            <Radio className="size-3" /> {transport === "sse" ? t.monitor.liveSse : t.monitor.livePolling}
          </Badge>
        ) : null}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t.campaigns.monitor}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <ol className="flex flex-wrap gap-1.5" aria-label={t.campaigns.currentStage}>
            {STAGES.map((st, i) => {
              const done = c.stage === "done" || (stageIdx >= 0 && i < stageIdx);
              const current = st === c.stage && c.stage !== "done";
              return (
                <li key={st}>
                  <Badge tone={current ? "yellow" : done ? "blue" : "neutral"} aria-current={current ? "step" : undefined}>
                    {done ? <CheckCircle2 className="size-3" /> : current ? <CircleDot className="size-3 animate-pulse" /> : null}
                    {label(st)}
                  </Badge>
                </li>
              );
            })}
          </ol>
          <div>
            <div className="mb-1.5 flex justify-between text-xs text-muted-foreground">
              <span>
                {live.activity
                  ? eventText(live.activity_t, live.activity)
                  : running
                    ? t.campaigns.indeterminate
                    : (t.status[c.status] ?? label(c.status))}
              </span>
              <span className="tabular-nums">
                {s.progress?.percent !== null && s.progress?.percent !== undefined
                  ? `${s.progress.completed_units}/${s.progress.total_units} ${t.monitor.units} · ${s.progress.percent}%`
                  : t.campaigns.indeterminate}
              </span>
            </div>
            <Progress value={c.status === "draft" ? 0 : s.progress?.percent ?? null} label={t.campaigns.progress} />
            {live.provider ? <p className="mt-1.5 text-xs text-muted-foreground">{t.monitor.provider}: {source(live.provider)}</p> : null}
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
            <Metric label={t.campaigns.requestedVsFound} value={`${s.target ?? c.settings.target_count} / ${s.unique_leads ?? 0}`} />
            <Metric label={t.campaigns.discovered} value={s.discovered ?? 0} hint={`${t.monitor.dupesRemoved}: ${s.duplicates_removed ?? 0}`} />
            <Metric label={t.monitor.enriched} value={s.enriched ?? 0} />
            <Metric label={t.monitor.contactsFound} value={s.contacts_found ?? 0} hint={`${s.businesses_with_contacts ?? 0} ${t.monitor.businesses}`} />
            <Metric label={t.monitor.emails} value={s.emails_found ?? 0} hint={`${t.monitor.verified}: ${s.verified_emails ?? 0}`} />
            <Metric label={t.monitor.analyses} value={s.analyzed ?? 0} />
            <Metric label={t.campaigns.qualified} value={s.qualified ?? 0} hint={`${t.monitor.high}: ${s.high_priority ?? 0}`} />
            {platformAdmin ? (
              <Metric label={t.campaigns.cost} value={formatMoney(c.cost_discovery + c.cost_ai)} hint={`${t.labels.ai} ${formatMoney(c.cost_ai)}`} />
            ) : null}
          </div>
          {/* Stopped for lack of credits: offer the top-up. Other technical reasons (which provider failed) are
              for platform admins; customers already see the "partially completed" status. */}
          {c.last_error?.includes("Credits exhausted") ? <OutOfCredits stopped /> : null}
          {c.last_error && platformAdmin && !c.last_error.includes("Credits exhausted") ? (
            <p className="flex items-start gap-2 rounded-md border border-sun-500/30 bg-sun-500/10 p-3 text-xs">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" /> {c.last_error}
            </p>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="mb-2 text-xs font-medium">{t.campaigns.sources}</p>
              <ul className="space-y-1.5">
                {c.sources.map((src) => (
                  <li key={src.provider_key} className="flex items-center justify-between gap-2 rounded-md border p-2 text-xs">
                    <span className="font-medium">{source(src.provider_key)}</span>
                    <span className="flex items-center gap-2 text-muted-foreground">
                      {src.results_count} {t.monitor.results}
                      <Badge tone={src.status === "done" ? "green" : src.status === "failed" ? "red" : src.status === "skipped" ? "yellow" : "neutral"}>
                        {label(src.status)}
                      </Badge>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="mb-2 text-xs font-medium">{t.monitor.warnings} ({warnings.length}) · {t.monitor.rateLimits}: {s.rate_limit_warnings ?? 0}</p>
              <ul className="max-h-40 space-y-1 overflow-y-auto text-xs">
                {warnings.slice(-8).map((w) => (
                  <li key={w.id} className="flex gap-1.5">
                    {w.level === "error" ? <XCircle className="size-3.5 shrink-0 text-destructive" /> : <AlertTriangle className="size-3.5 shrink-0 text-warning" />}
                    {eventText(w.data, w.message)}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-1">
          <CardHeader>
            <CardTitle>{t.campaigns.activity}</CardTitle>
          </CardHeader>
          <CardContent>
            <ol ref={logRef} className="max-h-[480px] space-y-2 overflow-y-auto pe-1 text-xs" aria-live="polite">
              {events.map((e) => (
                <li key={e.id} className="flex gap-2">
                  {e.level === "error" ? (
                    <XCircle className="mt-0.5 size-3.5 shrink-0 text-destructive" />
                  ) : e.level === "warning" ? (
                    <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />
                  ) : (
                    <Info className="mt-0.5 size-3.5 shrink-0 text-primary" />
                  )}
                  <div>
                    <p>{eventText(e.data, e.message)}</p>
                    <p className="text-muted-foreground">
                      {label(e.stage)} · {new Date(e.created_at).toLocaleTimeString(locale)}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>{t.campaigns.results}</CardTitle>
            <Link href={`/app/leads?campaign_id=${c.id}`} className="text-xs text-primary hover:underline">
              {t.campaigns.viewResults} →
            </Link>
          </CardHeader>
          <CardContent>
            <LeadsTable campaignId={c.id} compact />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
