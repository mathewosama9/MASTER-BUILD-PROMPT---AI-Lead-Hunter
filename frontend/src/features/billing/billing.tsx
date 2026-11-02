"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Coins, Hourglass, Infinity as Unlimited, ShieldCheck } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Table, Td, Th } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { PackageCard, popularIndex } from "@/features/billing/package-card";
import { useBillingSummary, useMe } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api, API_BASE, ApiError } from "@/lib/api";
import { cn, formatDate, formatNumber, formatPrice } from "@/lib/utils";
import type { CreditPackage, CreditTransaction, Page, TopUp, TopUpStatus } from "@/types/api";

const STATUS_TONE: Record<TopUpStatus, "yellow" | "green" | "red"> = { pending: "yellow", approved: "green", rejected: "red" };

export function BillingPage() {
  const { t } = useI18n();
  const summary = useBillingSummary();
  if (summary.isLoading) return <LoadingState />;
  if (summary.error || !summary.data) return <ErrorState error={summary.error} onRetry={() => summary.refetch()} />;
  const s = summary.data;

  return (
    <div className="space-y-6">
      <PageHeader title={t.billing.title} subtitle={t.billing.subtitle} />
      {s.billing_exempt ? (
        <Card>
          <CardContent className="flex items-center gap-3 p-5 text-sm">
            <Unlimited className="size-5 text-rasd-500" aria-hidden /> {t.billing.exempt}
          </CardContent>
        </Card>
      ) : (
        <>
          <StatusCards />
          <Packages />
        </>
      )}
      <Ledger />
    </div>
  );
}

function StatusCards() {
  const { t, locale } = useI18n();
  const { data: s } = useBillingSummary();
  if (!s) return null;
  return (
    <div className={cn("grid gap-4", s.pending_topups ? "md:grid-cols-3" : "md:grid-cols-2")}>
      <Card className={cn(s.low_balance && "border-sun-500/60")}>
        <CardContent className="p-5">
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Coins className="size-4" aria-hidden /> {t.billing.balance}
          </p>
          <p className="mt-2 text-3xl font-bold tabular-nums">{formatNumber(s.balance, locale)}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {t.billing.perContact.replace("{n}", String(s.credits_per_contact))}
          </p>
          {s.low_balance ? (
            <p className="mt-3 flex items-center gap-1.5 text-xs font-medium text-[#7a5700] dark:text-sun-400">
              <AlertTriangle className="size-3.5" aria-hidden /> {t.billing.lowBalance}
            </p>
          ) : null}
        </CardContent>
      </Card>
      <Card className={cn(s.trial_expired && "border-rose-500/60")}>
        <CardContent className="p-5">
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Hourglass className="size-4" aria-hidden /> {t.billing.plan}
          </p>
          {s.awaiting_verification ? (
            <>
              <p className="mt-2 text-lg font-semibold">{t.account.awaitingTrial}</p>
              <p className="mt-1 text-xs text-muted-foreground">{t.account.awaitingTrialHint}</p>
            </>
          ) : s.on_trial ? (
            s.trial_expired ? (
              <p className="mt-2 text-lg font-semibold text-destructive">{t.billing.trialExpired}</p>
            ) : (
              <>
                <p className="mt-2 text-lg font-semibold">
                  {t.billing.trialDaysLeft.replace("{n}", String(s.trial_days_left ?? 0))}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t.billing.trialEnds.replace("{date}", formatDate(s.trial_ends_at, locale))}
                </p>
              </>
            )
          ) : (
            <p className="mt-2 flex items-center gap-2 text-lg font-semibold">
              <CheckCircle2 className="size-5 text-success" aria-hidden /> {t.billing.paidPlan}
            </p>
          )}
        </CardContent>
      </Card>
      {/* Legacy manual transfers still awaiting review; PayPal payments are confirmed instantly. */}
      {s.pending_topups ? (
        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground">{t.billing.pendingRequests}</p>
            <p className="mt-2 text-3xl font-bold tabular-nums">{s.pending_topups}</p>
            <p className="mt-1 text-xs text-muted-foreground">{t.billing.pendingHint}</p>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

/** Back from PayPal: /app/billing?paypal=return|cancel&token=<order id>. Capture (or close) the order once. */
function usePayPalReturn() {
  const { t } = useI18n();
  const params = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const handled = useRef(false);
  const outcome = params.get("paypal");
  const orderId = params.get("token");
  const settle = useMutation({
    mutationFn: (action: "capture" | "cancel") =>
      api<TopUp>(`/billing/paypal/${action}`, { method: "POST", body: { order_id: orderId } }),
    onSuccess: (topup, action) => {
      if (action === "capture") toast.success(t.billing.paypalPaid.replace("{n}", formatNumber(topup.credits)));
      else toast.message(t.billing.paypalCancelled);
      ["billing-summary", "billing-topups", "billing-transactions"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    },
    onError: (e: Error) => toast.error(e.message),
    onSettled: () => router.replace("/app/billing"),
  });
  useEffect(() => {
    if (handled.current || !orderId || (outcome !== "return" && outcome !== "cancel")) return;
    handled.current = true;
    settle.mutate(outcome === "return" ? "capture" : "cancel");
  }, [orderId, outcome, settle]);
  return settle.isPending && settle.variables === "capture";
}

function Packages() {
  const { t } = useI18n();
  const { data: me } = useMe();
  const { data: s } = useBillingSummary();
  const params = useSearchParams();
  const packages = useQuery({ queryKey: ["billing-packages"], queryFn: () => api<CreditPackage[]>("/billing/packages") });
  const capturing = usePayPalReturn();
  const canRequest = me?.role === "owner" || me?.role === "admin";
  const paypalReady = !!s?.paypal_enabled;
  // A package chosen on the public pricing page arrives as ?pkg=<id>.
  const preselected = params.get("pkg");

  const checkout = useMutation({
    mutationFn: (pkg: CreditPackage) =>
      api<{ order_id: string; approve_url: string }>("/billing/paypal/orders", { method: "POST", body: { package_id: pkg.id } }),
    onSuccess: (o) => window.location.assign(o.approve_url),
    onError: (e: Error) => toast.error(e instanceof ApiError && e.code === "payments_unavailable" ? t.billing.paypalUnavailable : e.message),
  });

  const popular = packages.data ? popularIndex(packages.data) : -1;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.billing.packages}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {capturing ? (
          <p className="flex items-center gap-2 rounded-lg border bg-muted/50 p-3 text-sm" role="status">
            <Spinner /> {t.billing.paypalCapturing}
          </p>
        ) : null}
        {packages.isLoading ? (
          <LoadingState rows={2} />
        ) : packages.error ? (
          <ErrorState error={packages.error} onRetry={() => packages.refetch()} />
        ) : !packages.data?.length ? (
          <EmptyState title={t.billing.noPackages} />
        ) : (
          <div className="grid gap-4 pt-2 sm:grid-cols-2 lg:grid-cols-3">
            {packages.data.map((p, i) => {
              const busy = checkout.isPending && checkout.variables?.id === p.id;
              return (
                <PackageCard key={p.id} pkg={p} hot={i === popular} selected={p.id === preselected} compact>
                  {canRequest ? (
                    <Button
                      type="button"
                      className="w-full"
                      variant={p.id === preselected || i === popular ? "accent" : "outline"}
                      disabled={!paypalReady || checkout.isPending || capturing}
                      onClick={() => checkout.mutate(p)}
                    >
                      {busy ? <Spinner /> : null} {busy ? t.billing.paypalRedirecting : t.billing.payPayPal}
                    </Button>
                  ) : null}
                </PackageCard>
              );
            })}
          </div>
        )}
        {!canRequest ? (
          <p className="text-xs text-muted-foreground">{t.billing.adminsOnly}</p>
        ) : !paypalReady ? (
          <p className="text-sm text-muted-foreground">{t.billing.paypalUnavailable}</p>
        ) : (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <ShieldCheck className="size-4 text-rasd-500" aria-hidden /> {t.billing.paypalSecure}
          </p>
        )}
        <MyRequests />
      </CardContent>
    </Card>
  );
}

function MyRequests() {
  const { t, locale, label } = useI18n();
  const q = useQuery({ queryKey: ["billing-topups"], queryFn: () => api<TopUp[]>("/billing/topups") });
  if (!q.data?.length) return null;
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">{t.billing.myRequests}</h3>
      <div className="overflow-x-auto">
        <Table>
          <thead>
            <tr>
              <Th>{t.billing.date}</Th>
              <Th>{t.billing.credits}</Th>
              <Th>{t.billing.amount}</Th>
              <Th>{t.billing.method}</Th>
              <Th>{t.billing.status}</Th>
              <Th>{t.billing.receipt}</Th>
            </tr>
          </thead>
          <tbody>
            {q.data.map((r) => (
              <tr key={r.id}>
                <Td className="whitespace-nowrap">{formatDate(r.created_at, locale)}</Td>
                <Td className="tabular-nums">{formatNumber(r.credits, locale)}</Td>
                <Td className="whitespace-nowrap tabular-nums">{formatPrice(r.amount, r.currency)}</Td>
                <Td>{label(r.method)}</Td>
                <Td>
                  <Badge tone={STATUS_TONE[r.status]}>{label(r.status)}</Badge>
                  {r.status === "rejected" && r.reason ? <p className="mt-1 text-xs text-muted-foreground">{r.reason}</p> : null}
                </Td>
                <Td>
                  {r.receipt_filename ? (
                    <a
                      href={`${API_BASE}/billing/topups/${r.id}/receipt`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-rasd-600 underline-offset-2 hover:underline dark:text-rasd-300"
                    >
                      {t.billing.view}
                    </a>
                  ) : (
                    "—"
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </div>
  );
}

function Ledger() {
  const { t, locale, label } = useI18n();
  const [page, setPage] = useState(1);
  const q = useQuery({
    queryKey: ["billing-transactions", page],
    queryFn: () => api<Page<CreditTransaction>>("/billing/transactions", { query: { page, page_size: 20 } }),
  });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.billing.history}</CardTitle>
      </CardHeader>
      <CardContent>
        {q.isLoading ? (
          <LoadingState rows={3} />
        ) : q.error ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : !q.data?.items.length ? (
          <EmptyState title={t.billing.noHistory} />
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table>
                <thead>
                  <tr>
                    <Th>{t.billing.date}</Th>
                    <Th>{t.billing.type}</Th>
                    <Th>{t.billing.change}</Th>
                    <Th>{t.billing.balanceAfter}</Th>
                    <Th>{t.billing.note}</Th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.items.map((x) => (
                    <tr key={x.id}>
                      <Td className="whitespace-nowrap">{formatDate(x.created_at, locale)}</Td>
                      <Td>{label(x.kind)}</Td>
                      <Td className={cn("tabular-nums font-medium", x.delta > 0 ? "text-success" : "text-foreground")} dir="ltr">
                        {x.delta > 0 ? `+${x.delta}` : x.delta}
                      </Td>
                      <Td className="tabular-nums">{formatNumber(x.balance_after, locale)}</Td>
                      <Td className="text-xs text-muted-foreground">{x.note ?? "—"}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
            {pages > 1 ? (
              <div className="mt-3 flex items-center justify-end gap-2 text-xs">
                <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  {t.common.back}
                </Button>
                <span className="tabular-nums">
                  {page} / {pages}
                </span>
                <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                  {t.billing.next}
                </Button>
              </div>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
