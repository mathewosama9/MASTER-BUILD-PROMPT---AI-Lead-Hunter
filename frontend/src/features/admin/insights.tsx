"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Banknote, CheckCircle2, Coins, Inbox, MessageSquareQuote, UserPlus, Users, Wallet } from "lucide-react";

import { TrendChart } from "@/components/charts";
import { Card, CardContent, CardHeader, CardTitle, Table, Td, Th } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn, formatMoney, formatNumber } from "@/lib/utils";

interface Money {
  currency: string;
  amount: number;
}
interface AdminOverview {
  users: { last_7d: number; last_30d: number; total: number };
  workspaces: { total: number; active_30d: number };
  revenue: { last_30d: Money[]; total: Money[]; monthly: (Money & { month: string })[] };
  credits_used_30d: number;
  attention: { pending_topups: number; new_contacts: number; pending_reviews: number; sample_reviews: number };
  funnel: { signed_up: number; verified: number; first_search: number; paid: number };
  daily: { date: string; signups: number; credits_used: number }[];
}
interface UsageRow {
  workspace_id: string;
  name: string;
  billing_exempt: boolean;
  credits_used: number;
  discovery_cost_usd: number;
  ai_cost_usd: number;
  revenue: number;
  currency: string | null;
}

export type AdminTab = "overview" | "topups" | "workspaces" | "packages" | "contacts" | "testimonials" | "providers" | "usage" | "settings";

function money(list: Money[], locale: string) {
  return list.length ? list.map((m) => `${formatNumber(m.amount, locale)} ${m.currency}`).join(" + ") : "0";
}

function Tile({
  label,
  value,
  hint,
  icon: Icon,
  dark,
}: {
  label: string;
  value: string;
  hint: string;
  icon: React.ComponentType<{ className?: string }>;
  dark?: boolean;
}) {
  return (
    <Card className={cn(dark && "border-ink-900 bg-ink-900 text-paper")}>
      <CardContent className="p-5">
        <div className="flex items-center justify-between">
          <p className={cn("text-sm", dark ? "text-mist-300" : "text-muted-foreground")}>{label}</p>
          <span className={cn("rounded-lg p-2", dark ? "bg-white/10 text-signal-400" : "bg-rasd-50 text-rasd-700 dark:bg-rasd-500/10 dark:text-rasd-300")}>
            <Icon className="size-4" />
          </span>
        </div>
        <p className="mt-3 font-display text-2xl font-bold tabular-nums tracking-tight">{value}</p>
        <p className={cn("mt-1 text-xs", dark ? "text-mist-300" : "text-muted-foreground")}>{hint}</p>
      </CardContent>
    </Card>
  );
}

export function AdminOverviewTab({ go }: { go: (tab: AdminTab) => void }) {
  const { t, locale } = useI18n();
  const o = t.admin.ov;
  const q = useQuery({ queryKey: ["admin-overview"], queryFn: () => api<AdminOverview>("/admin/overview"), refetchInterval: 60_000 });
  if (q.isLoading) return <LoadingState rows={6} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data;
  const n = (v: number) => formatNumber(v, locale);
  const attention = [
    { n: d.attention.pending_topups, text: o.pendingTopups, tab: "topups" as const, icon: Wallet },
    { n: d.attention.new_contacts, text: o.newContacts, tab: "contacts" as const, icon: Inbox },
    { n: d.attention.pending_reviews, text: o.pendingReviews, tab: "testimonials" as const, icon: MessageSquareQuote },
  ].filter((x) => x.n > 0);
  const steps = (["signed_up", "verified", "first_search", "paid"] as const).map((k) => ({ k, v: d.funnel[k] }));
  const top = Math.max(1, d.funnel.signed_up);

  return (
    <div className="space-y-6">
      {d.attention.sample_reviews > 0 ? (
        <button
          type="button"
          onClick={() => go("testimonials")}
          className="flex w-full items-start gap-3 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-start text-sm text-rose-800 dark:text-rose-200"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          {o.sampleReviews.replace("{n}", n(d.attention.sample_reviews))}
        </button>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Tile
          dark
          label={o.revenue}
          value={money(d.revenue.last_30d, locale)}
          hint={o.revenueHint.replace("{total}", money(d.revenue.total, locale))}
          icon={Banknote}
        />
        <Tile
          label={o.users}
          value={n(d.users.last_30d)}
          hint={o.usersHint.replace("{n}", n(d.users.last_7d)).replace("{total}", n(d.users.total))}
          icon={UserPlus}
        />
        <Tile
          label={o.workspaces}
          value={n(d.workspaces.active_30d)}
          hint={o.workspacesHint.replace("{total}", n(d.workspaces.total))}
          icon={Users}
        />
        <Tile label={o.credits} value={n(d.credits_used_30d)} hint={o.creditsHint} icon={Coins} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>{o.attention}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {attention.length === 0 ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <CheckCircle2 className="size-4 text-success" /> {o.allClear}
              </p>
            ) : (
              attention.map((a) => (
                <button
                  key={a.tab}
                  type="button"
                  onClick={() => go(a.tab)}
                  className="flex w-full items-center gap-3 rounded-xl border p-3 text-start text-sm hover:bg-muted"
                >
                  <span className="flex size-8 items-center justify-center rounded-lg bg-sun-500/15 text-[#7a5700] dark:text-sun-400">
                    <a.icon className="size-4" />
                  </span>
                  {a.text.replace("{n}", n(a.n))}
                </button>
              ))
            )}
          </CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{o.funnel}</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="space-y-3">
              {steps.map(({ k, v }, i) => (
                <li key={k}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span>
                      {i + 1}. {o.funnelSteps[k]}
                    </span>
                    <span className="tabular-nums">
                      {n(v)}
                      {i > 0 ? <span className="ms-2 text-xs text-muted-foreground">{Math.round((v / top) * 100)}%</span> : null}
                    </span>
                  </div>
                  <div className="h-2.5 overflow-hidden rounded-full bg-muted">
                    <div className={cn("h-full rounded-full", k === "paid" ? "bg-signal-500" : "bg-rasd-600")} style={{ width: `${(v / top) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>
              {o.signups} · {o.daily}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <TrendChart data={d.daily.map((x) => ({ date: x.date, count: x.signups }))} label={o.signups} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>
              {o.creditsUsed} · {o.daily}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <TrendChart data={d.daily.map((x) => ({ date: x.date, count: x.credits_used }))} label={o.creditsUsed} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{o.monthly}</CardTitle>
        </CardHeader>
        <CardContent>
          {d.revenue.monthly.length === 0 ? (
            <p className="text-sm text-muted-foreground">{o.noRevenue}</p>
          ) : (
            <ul className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
              {d.revenue.monthly.map((m) => (
                <li key={`${m.month}-${m.currency}`} className="rounded-xl border p-3">
                  <p className="text-xs text-muted-foreground">{m.month}</p>
                  <p className="mt-1 font-display font-semibold tabular-nums">
                    {formatNumber(m.amount, locale)} {m.currency}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function UsageTab() {
  const { t, locale } = useI18n();
  const u = t.admin.usage;
  const q = useQuery({ queryKey: ["admin-usage"], queryFn: () => api<UsageRow[]>("/admin/usage") });
  if (q.isLoading) return <LoadingState rows={6} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{u.title}</CardTitle>
        <p className="text-sm text-muted-foreground">{u.hint}</p>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        {q.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">{u.empty}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t.admin.workspace}</Th>
                <Th className="text-end">{u.credits}</Th>
                <Th className="text-end">{u.revenue}</Th>
                <Th className="text-end">{u.discovery}</Th>
                <Th className="text-end">{u.ai}</Th>
                <Th className="text-end">{u.totalCost}</Th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((r) => (
                <tr key={r.workspace_id} className="border-t">
                  <Td>
                    <span className="font-medium">{r.name}</span>
                    {r.billing_exempt ? <span className="ms-2 text-xs text-muted-foreground">({t.admin.exempt})</span> : null}
                  </Td>
                  <Td className="text-end tabular-nums">{formatNumber(r.credits_used, locale)}</Td>
                  <Td className="text-end tabular-nums">{r.revenue ? `${formatNumber(r.revenue, locale)} ${r.currency ?? ""}` : "—"}</Td>
                  <Td className="text-end tabular-nums">{formatMoney(r.discovery_cost_usd)}</Td>
                  <Td className="text-end tabular-nums">{formatMoney(r.ai_cost_usd)}</Td>
                  <Td className="text-end font-medium tabular-nums">{formatMoney(r.discovery_cost_usd + r.ai_cost_usd)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
