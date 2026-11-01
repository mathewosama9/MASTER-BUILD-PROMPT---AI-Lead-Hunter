"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Clock,
  Coins,
  Copy,
  FileText,
  Hourglass,
  Infinity as Unlimited,
  Landmark,
  Smartphone,
  Upload,
  Wallet,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Field, Input, Table, Td, Th } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { PackageCard, popularIndex } from "@/features/billing/package-card";
import { useBillingSummary, useMe } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api, API_BASE, ApiError } from "@/lib/api";
import { cn, formatDate, formatNumber } from "@/lib/utils";
import type { CreditPackage, CreditTransaction, Page, PaymentMethod, TopUp, TopUpStatus } from "@/types/api";

const MAX_RECEIPT_BYTES = 5 * 1024 * 1024;
const ACCEPTED_RECEIPTS = ["image/png", "image/jpeg", "image/webp", "application/pdf"];
const METHODS: PaymentMethod[] = ["instapay", "vodafone_cash", "bank_transfer"];
const STATUS_TONE: Record<TopUpStatus, "yellow" | "green" | "red"> = { pending: "yellow", approved: "green", rejected: "red" };

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

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
    <div className="grid gap-4 md:grid-cols-3">
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
      <Card>
        <CardContent className="p-5">
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <FileText className="size-4" aria-hidden /> {t.billing.pendingRequests}
          </p>
          <p className="mt-2 text-3xl font-bold tabular-nums">{s.pending_topups}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t.billing.pendingHint}</p>
        </CardContent>
      </Card>
    </div>
  );
}

function Packages() {
  const { t } = useI18n();
  const { data: me } = useMe();
  const params = useSearchParams();
  const packages = useQuery({ queryKey: ["billing-packages"], queryFn: () => api<CreditPackage[]>("/billing/packages") });
  const [picked, setPicked] = useState<string | null>(null);
  const formRef = useRef<HTMLDivElement>(null);
  const canRequest = me?.role === "owner" || me?.role === "admin";
  // A package chosen on the public pricing page arrives as ?pkg=<id>.
  const selectedId = picked ?? params.get("pkg");
  const selected = packages.data?.find((p) => p.id === selectedId) ?? null;

  useEffect(() => {
    if (selected && canRequest) formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [selected, canRequest]);

  const popular = packages.data ? popularIndex(packages.data) : -1;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.billing.packages}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {packages.isLoading ? (
          <LoadingState rows={2} />
        ) : packages.error ? (
          <ErrorState error={packages.error} onRetry={() => packages.refetch()} />
        ) : !packages.data?.length ? (
          <EmptyState title={t.billing.noPackages} />
        ) : (
          <div className="grid gap-4 pt-2 sm:grid-cols-2 lg:grid-cols-3">
            {packages.data.map((p, i) => {
              const active = selected?.id === p.id;
              return (
                <PackageCard key={p.id} pkg={p} hot={i === popular} selected={active} compact>
                  {canRequest ? (
                    <Button
                      type="button"
                      className="w-full"
                      variant={active || i === popular ? "accent" : "outline"}
                      aria-pressed={active}
                      onClick={() => setPicked(p.id)}
                    >
                      {active ? (
                        <>
                          <Check /> {t.billing.chosen}
                        </>
                      ) : (
                        t.billing.choose
                      )}
                    </Button>
                  ) : null}
                </PackageCard>
              );
            })}
          </div>
        )}
        {!canRequest ? (
          <p className="text-xs text-muted-foreground">{t.billing.adminsOnly}</p>
        ) : !selected && packages.data?.length ? (
          <p className="text-sm text-muted-foreground">{t.billing.pickToPay}</p>
        ) : null}
        <div ref={formRef} className="scroll-mt-24">
          {selected && canRequest ? <TopUpForm key={selected.id} pkg={selected} onDone={() => setPicked("")} /> : null}
        </div>
        <MyRequests />
      </CardContent>
    </Card>
  );
}

const METHOD_ICONS: Record<PaymentMethod, React.ComponentType<{ className?: string }>> = {
  instapay: Smartphone,
  vodafone_cash: Wallet,
  bank_transfer: Landmark,
};

function CopyButton({ text, label }: { text: string; label?: string }) {
  const { t } = useI18n();
  const [done, setDone] = useState(false);
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      className="shrink-0"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          toast.error(text);
        }
      }}
      aria-label={label ? `${t.billing.copy}: ${label}` : t.billing.copy}
    >
      {done ? <Check /> : <Copy />} {done ? t.billing.copied : t.billing.copy}
    </Button>
  );
}

function ReceiptDrop({ file, onFile, error }: { file: File | null; onFile: (f: File | null) => void; error?: string }) {
  const { t } = useI18n();
  const [drag, setDrag] = useState(false);
  const preview = useMemo(() => (file && file.type.startsWith("image/") ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview);
    };
  }, [preview]);

  return (
    <div>
      <label
        htmlFor="topup_receipt"
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          onFile(e.dataTransfer.files?.[0] ?? null);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed bg-card p-5 text-center text-sm transition-colors focus-within:ring-2 focus-within:ring-ring",
          drag ? "border-rasd-500 bg-rasd-50 dark:bg-rasd-500/10" : "hover:border-rasd-500/60",
          error && "border-destructive",
        )}
      >
        {file ? (
          <>
            {preview ? (
              // eslint-disable-next-line @next/next/no-img-element -- a local object URL, nothing for next/image to optimise
              <img src={preview} alt="" className="max-h-40 rounded-md border object-contain" />
            ) : (
              <FileText className="size-10 text-muted-foreground" aria-hidden />
            )}
            <span className="max-w-full truncate font-medium" dir="ltr">
              {file.name}
            </span>
            <span className="text-xs text-primary">{t.billing.changeReceipt}</span>
          </>
        ) : (
          <>
            <Upload className="size-8 text-muted-foreground" aria-hidden />
            <span className="font-medium">{t.billing.dropReceipt}</span>
            <span className="text-xs text-muted-foreground">{t.billing.receiptHint}</span>
          </>
        )}
        <input
          id="topup_receipt"
          type="file"
          className="sr-only"
          aria-label={t.billing.receipt}
          accept={ACCEPTED_RECEIPTS.join(",")}
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        />
      </label>
      {error ? (
        <p role="alert" className="mt-1.5 text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function TopUpForm({ pkg, onDone }: { pkg: CreditPackage; onDone: () => void }) {
  const { t, locale, label } = useI18n();
  const { data: s } = useBillingSummary();
  const qc = useQueryClient();
  const [method, setMethod] = useState<PaymentMethod>("instapay");
  const [reference, setReference] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const instructions = (locale === "ar" ? s?.payment_instructions_ar : s?.payment_instructions_en)?.trim();
  const amount = `${formatNumber(Number(pkg.price), locale)} ${pkg.currency}`;

  function pickFile(f: File | null) {
    if (!f) return;
    const error = f.size > MAX_RECEIPT_BYTES ? t.validation.fileTooLarge : !ACCEPTED_RECEIPTS.includes(f.type) ? t.billing.receiptType : null;
    setFileError(error);
    setFile(error ? null : f);
  }

  const submit = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error(t.billing.receiptRequired);
      const receipt_base64 = await toBase64(file);
      return api<TopUp>("/billing/topups", {
        method: "POST",
        body: { package_id: pkg.id, method, reference: reference || null, receipt_filename: file.name, receipt_base64 },
      });
    },
    onSuccess: () => {
      toast.success(t.billing.requestSent);
      qc.invalidateQueries({ queryKey: ["billing-topups"] });
      qc.invalidateQueries({ queryKey: ["billing-summary"] });
      onDone();
    },
    onError: (e: Error) => {
      if (e instanceof ApiError && e.code === "unsupported_receipt") toast.error(t.billing.receiptType);
      else if (e instanceof ApiError && e.code === "too_many_pending") toast.error(t.billing.tooManyPending);
      else toast.error(e.message);
    },
  });

  return (
    <form
      className="space-y-5 rounded-2xl border bg-muted/40 p-5"
      onSubmit={(e) => {
        e.preventDefault();
        submit.mutate();
      }}
    >
      <p className="text-sm font-medium">
        {t.billing.payFor.replace("{name}", locale === "ar" ? pkg.name_ar : pkg.name_en).replace("{price}", amount)}
      </p>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold">{t.billing.method}</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {METHODS.map((m) => {
            const Icon = METHOD_ICONS[m];
            return (
              <label
                key={m}
                className={cn(
                  "flex cursor-pointer items-center gap-2.5 rounded-xl border bg-card p-3 text-sm transition-colors focus-within:ring-2 focus-within:ring-ring",
                  method === m ? "border-rasd-500 bg-rasd-50 font-medium dark:bg-rasd-500/10" : "hover:border-rasd-500/50",
                )}
              >
                <input type="radio" name="topup_method" value={m} checked={method === m} onChange={() => setMethod(m)} className="sr-only" />
                <Icon className="size-4 text-rasd-600 dark:text-rasd-300" aria-hidden /> {label(m)}
              </label>
            );
          })}
        </div>
      </fieldset>

      <div className="space-y-3">
        <p className="text-sm font-semibold">1. {t.billing.stepPay}</p>
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-4">
          <div>
            <p className="text-xs text-muted-foreground">{t.billing.transferAmount}</p>
            <p className="font-display text-2xl font-bold tabular-nums">{amount}</p>
          </div>
          <CopyButton text={String(Number(pkg.price))} label={t.billing.transferAmount} />
        </div>
        {instructions ? (
          <div className="flex items-start justify-between gap-3 rounded-xl border bg-card p-4">
            <p className="whitespace-pre-line text-sm leading-relaxed">{instructions}</p>
            <CopyButton text={instructions} />
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">{t.billing.noInstructions}</p>
        )}
      </div>

      <div className="space-y-3">
        <p className="text-sm font-semibold">2. {t.billing.stepReceipt}</p>
        <ReceiptDrop file={file} onFile={pickFile} error={fileError ?? undefined} />
        <Field label={t.billing.reference} htmlFor="topup_reference" hint={t.billing.referenceHint}>
          <Input id="topup_reference" dir="ltr" maxLength={200} value={reference} onChange={(e) => setReference(e.target.value)} />
        </Field>
      </div>

      <p className="flex items-start gap-2 rounded-lg bg-card p-3 text-xs text-muted-foreground">
        <Clock className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {t.billing.approvalTime}
      </p>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={submit.isPending || !file}>
          {submit.isPending ? <Spinner /> : null} {t.billing.sendRequest}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          {t.common.cancel}
        </Button>
      </div>
    </form>
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
                <Td className="whitespace-nowrap tabular-nums">
                  {formatNumber(Number(r.amount), locale)} {r.currency}
                </Td>
                <Td>{label(r.method)}</Td>
                <Td>
                  <Badge tone={STATUS_TONE[r.status]}>{label(r.status)}</Badge>
                  {r.status === "rejected" && r.reason ? <p className="mt-1 text-xs text-muted-foreground">{r.reason}</p> : null}
                </Td>
                <Td>
                  <a
                    href={`${API_BASE}/billing/topups/${r.id}/receipt`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-rasd-600 underline-offset-2 hover:underline dark:text-rasd-300"
                  >
                    {t.billing.view}
                  </a>
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
