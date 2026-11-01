"use client";

import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { DemoBadge, StatusBadge } from "@/components/badges";
import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, Input, Progress, Select, Table, Td, Th } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useCampaigns, useMeta, usePlatformAdmin } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { formatDate, formatMoney } from "@/lib/utils";

import { CampaignActions } from "./actions";

export function CampaignList() {
  const { t, locale, label, source } = useI18n();
  const platformAdmin = usePlatformAdmin();
  const { data: meta } = useMeta();
  const industryName = (k: string) => {
    const i = meta?.industries.find((x) => x.key === k);
    return i ? (locale === "ar" ? i.ar : i.en) : label(k);
  };
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const { data, isLoading, error, refetch } = useCampaigns({ q: q || undefined, status: status || undefined, page, page_size: 20 });

  return (
    <div>
      <PageHeader
        title={t.campaigns.title}
        subtitle={t.campaigns.subtitle}
        actions={
          <Button asChild variant="accent">
            <Link href="/app/campaigns/new">
              <Plus /> {t.campaigns.new}
            </Link>
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap gap-2">
        <div className="relative min-w-56 flex-1">
          <Search className="absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" name="q" autoComplete="off" aria-label={t.common.search} placeholder={t.common.search} className="ps-9" value={q}
                 onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        </div>
        <Select aria-label={t.campaigns.status} className="w-48" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">{t.common.all}</option>
          {Object.entries(t.status).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </Select>
      </div>
      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState title={t.campaigns.noCampaigns} action={<Button asChild><Link href="/app/campaigns/new">{t.campaigns.new}</Link></Button>} />
      ) : (
        <Card>
          <Table>
            <thead className="border-b">
              <tr>
                <Th>{t.campaigns.name}</Th>
                <Th>{t.campaigns.country}</Th>
                <Th>{t.campaigns.category}</Th>
                <Th>{t.campaigns.sources}</Th>
                <Th>{t.campaigns.status}</Th>
                <Th className="text-end">{t.campaigns.target}</Th>
                <Th className="text-end">{t.campaigns.discovered}</Th>
                <Th className="text-end">{t.campaigns.qualified}</Th>
                <Th className="w-36">{t.campaigns.progress}</Th>
                {platformAdmin ? <Th className="text-end">{t.campaigns.cost}</Th> : null}
                <Th>{t.campaigns.created}</Th>
                <Th><span className="sr-only">{t.common.actions}</span></Th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id} className="border-b last:border-0 hover:bg-muted/40">
                  <Td>
                    <Link href={`/app/campaigns/${c.id}`} className="font-medium hover:text-primary hover:underline">{c.name}</Link>
                    {c.is_demo ? <div className="mt-1"><DemoBadge /></div> : null}
                  </Td>
                  <Td>{c.country}{c.city ? ` · ${c.city}` : ""}</Td>
                  <Td>{industryName(c.industry)}</Td>
                  <Td className="text-xs text-muted-foreground">{[...new Set(c.sources.map((s) => source(s.provider_key)))].join(locale === "ar" ? "، " : ", ")}</Td>
                  <Td><StatusBadge status={c.status} /></Td>
                  <Td className="text-end tabular-nums">{c.stats?.target ?? c.settings.target_count}</Td>
                  <Td className="text-end tabular-nums">{c.stats?.unique_leads ?? 0}</Td>
                  <Td className="text-end tabular-nums">{c.stats?.qualified ?? 0}</Td>
                  <Td><Progress value={c.status === "draft" ? 0 : c.stats?.progress?.percent ?? null} label={c.name} /></Td>
                  {platformAdmin ? <Td className="text-end tabular-nums">{formatMoney(c.cost_discovery + c.cost_ai)}</Td> : null}
                  <Td className="whitespace-nowrap text-xs text-muted-foreground">{formatDate(c.created_at, locale)}</Td>
                  <Td><CampaignActions c={c} compact /></Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <div className="flex items-center justify-between border-t p-3 text-xs text-muted-foreground">
            <span>{t.common.total}: {data.total}</span>
            <div className="flex gap-1">
              <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t.common.back}</Button>
              <Button size="sm" variant="outline" disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}>{t.common.next}</Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
