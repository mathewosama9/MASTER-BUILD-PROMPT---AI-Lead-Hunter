"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  Bell,
  Building2,
  Check,
  ExternalLink,
  Inbox,
  KeyRound,
  LayoutDashboard,
  MessageSquareQuote,
  Package,
  Pencil,
  Plus,
  Radar,
  CreditCard,
  Settings2,
  ShieldCheck,
  ShieldOff,
  Users,
  Wallet,
  X,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardContent,
  Dialog,
  Field,
  Input,
  Switch,
  Table,
  Td,
  Textarea,
  Th,
} from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { useMe } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api, API_BASE } from "@/lib/api";
import { cn, formatDate, formatNumber, formatPrice } from "@/lib/utils";
import type { CreditPackage, Page, TopUp, TopUpStatus } from "@/types/api";

import { type AdminTab, AdminOverviewTab, UsageTab } from "./insights";
import { NotificationsAdmin } from "./notifications";
import { ActivityAdmin, CsvButton, JobsAdmin } from "./ops";
import { PayPalConnect } from "./paypal-connect";
import { ProvidersAdmin } from "./providers";
import { type ResearchDefaults, ResearchDefaultsEditor, researchDefaultsValid } from "./research-settings";
import { TestimonialsAdmin } from "./testimonials";
import { UsersAdmin } from "./users";

interface AdminTopUp extends TopUp {
  workspace_id: string;
  workspace_name: string;
  requested_by: string | null;
}
interface AdminPackage extends CreditPackage {
  active: boolean;
  sort: number;
}
interface AdminWorkspace {
  id: string;
  name: string;
  owner_email: string | null;
  created_at: string;
  balance: number;
  credits_used: number;
  campaigns: number;
  trial_ends_at: string | null;
  on_trial: boolean;
  billing_exempt: boolean;
  suspended_at: string | null;
  is_showcase: boolean;
}
interface PlatformSettings {
  trial_days: number;
  trial_credits: number;
  credits_per_contact: number;
  payment_instructions_ar: string;
  payment_instructions_en: string;
  signup_review: boolean;
  research_defaults: ResearchDefaults;
}
interface ContactRequest {
  id: string;
  name: string;
  company: string | null;
  email: string;
  phone: string | null;
  interest: string;
  message: string;
  locale: string;
  status: "new" | "handled";
  created_at: string;
}

const STATUS_TONE: Record<TopUpStatus, "yellow" | "green" | "red"> = { pending: "yellow", approved: "green", rejected: "red" };
const onError = (e: Error) => toast.error(e.message);

const TABS: { key: AdminTab; icon: React.ComponentType<{ className?: string }> }[] = [
  { key: "overview", icon: LayoutDashboard },
  { key: "users", icon: Users },
  { key: "topups", icon: Wallet },
  { key: "jobs", icon: Radar },
  { key: "workspaces", icon: Building2 },
  { key: "packages", icon: Package },
  { key: "contacts", icon: Inbox },
  { key: "testimonials", icon: MessageSquareQuote },
  { key: "providers", icon: KeyRound },
  { key: "usage", icon: BarChart3 },
  { key: "payments", icon: CreditCard },
  { key: "notifications", icon: Bell },
  { key: "activity", icon: Activity },
  { key: "settings", icon: Settings2 },
];

export function AdminPage() {
  const { t } = useI18n();
  const { data: me } = useMe();
  // A tab can be linked directly, e.g. /app/admin?tab=payments
  const [tab, setTab] = useState<AdminTab>(() => {
    const wanted = typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("tab");
    return TABS.some((x) => x.key === wanted) ? (wanted as AdminTab) : "overview";
  });
  if (!me) return <LoadingState rows={4} />;
  if (!me.user.is_superuser) return <EmptyState title={t.admin.forbidden} />;
  return (
    <div>
      <PageHeader title={t.admin.title} subtitle={t.admin.subtitle} />
      <div className="grid gap-6 lg:grid-cols-[13rem_1fr]">
        <nav aria-label={t.admin.title} className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1 lg:mx-0 lg:flex-col lg:overflow-visible lg:px-0">
          {TABS.map(({ key, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              aria-current={tab === key ? "page" : undefined}
              className={cn(
                "flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-start text-sm transition-colors",
                tab === key ? "bg-ink-900 font-medium text-paper dark:bg-paper dark:text-ink-900" : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="size-4" /> {t.admin.tabs[key]}
            </button>
          ))}
        </nav>
        <div className="min-w-0">
          {tab === "overview" ? <AdminOverviewTab go={setTab} /> : null}
          {tab === "users" ? <UsersAdmin /> : null}
          {tab === "topups" ? <TopUps /> : null}
          {tab === "jobs" ? <JobsAdmin /> : null}
          {tab === "activity" ? <ActivityAdmin /> : null}
          {tab === "workspaces" ? <Workspaces /> : null}
          {tab === "packages" ? <Packages /> : null}
          {tab === "contacts" ? <Contacts /> : null}
          {tab === "testimonials" ? <TestimonialsAdmin /> : null}
          {tab === "providers" ? <ProvidersAdmin /> : null}
          {tab === "usage" ? <UsageTab /> : null}
          {tab === "payments" ? <PayPalConnect /> : null}
          {tab === "notifications" ? <NotificationsAdmin /> : null}
          {tab === "settings" ? <SettingsForm /> : null}
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- top-ups */

function TopUps() {
  const { t, locale, label } = useI18n();
  const qc = useQueryClient();
  const [status, setStatus] = useState<TopUpStatus | "">("pending");
  const [rejecting, setRejecting] = useState<AdminTopUp | null>(null);
  const [reason, setReason] = useState("");
  const q = useQuery({
    queryKey: ["admin-topups", status],
    queryFn: () => api<AdminTopUp[]>("/admin/topups", { query: { status: status || undefined } }),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["admin-topups"] });
    qc.invalidateQueries({ queryKey: ["admin-workspaces"] });
  };
  const approve = useMutation({
    mutationFn: (id: string) => api<AdminTopUp>(`/admin/topups/${id}/approve`, { method: "POST" }),
    onSuccess: (r) => {
      toast.success(t.admin.approved.replace("{n}", String(r.credits)).replace("{ws}", r.workspace_name));
      refresh();
    },
    onError,
  });
  const reject = useMutation({
    mutationFn: () => api(`/admin/topups/${rejecting?.id}/reject`, { method: "POST", body: { reason } }),
    onSuccess: () => {
      toast.success(t.admin.rejected);
      setRejecting(null);
      setReason("");
      refresh();
    },
    onError,
  });

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <div className="flex flex-wrap gap-2">
          {(["pending", "approved", "rejected", ""] as const).map((s) => (
            <Button key={s || "all"} size="sm" variant={status === s ? "default" : "outline"} onClick={() => setStatus(s)}>
              {s ? label(s) : t.admin.all}
            </Button>
          ))}
          <div className="ms-auto">
            <CsvButton path="/admin/exports/payments.csv" query={{ status: status || undefined }} />
          </div>
        </div>
        {q.isLoading ? (
          <LoadingState rows={3} />
        ) : q.error ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : !q.data?.length ? (
          <EmptyState title={t.admin.noTopups} />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <thead>
                <tr>
                  <Th>{t.billing.date}</Th>
                  <Th>{t.admin.workspace}</Th>
                  <Th>{t.billing.credits}</Th>
                  <Th>{t.billing.amount}</Th>
                  <Th>{t.billing.method}</Th>
                  <Th>{t.billing.reference}</Th>
                  <Th>{t.billing.receipt}</Th>
                  <Th>{t.billing.status}</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {q.data.map((r) => (
                  <tr key={r.id}>
                    <Td className="whitespace-nowrap">{formatDate(r.created_at, locale)}</Td>
                    <Td>
                      <p className="font-medium">{r.workspace_name}</p>
                      <p className="text-xs text-muted-foreground">{r.requested_by}</p>
                    </Td>
                    <Td className="tabular-nums">{formatNumber(r.credits, locale)}</Td>
                    <Td className="whitespace-nowrap tabular-nums">{formatPrice(r.amount, r.currency)}</Td>
                    <Td>{label(r.method)}</Td>
                    <Td className="font-mono text-xs" dir="ltr">{r.reference ?? "—"}</Td>
                    <Td>
                      {r.receipt_filename ? (
                        <a
                          href={`${API_BASE}/admin/topups/${r.id}/receipt`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                        >
                          {t.billing.view} <ExternalLink className="size-3" aria-hidden />
                        </a>
                      ) : (
                        "—"
                      )}
                    </Td>
                    <Td>
                      <Badge tone={STATUS_TONE[r.status]}>{label(r.status)}</Badge>
                      {r.reason ? <p className="mt-1 max-w-48 text-xs text-muted-foreground">{r.reason}</p> : null}
                    </Td>
                    <Td>
                      {/* PayPal checkouts settle themselves; only manual transfers are reviewed by hand. */}
                      {r.status === "pending" && r.method !== "paypal" ? (
                        <div className="flex gap-1.5">
                          <Button size="sm" disabled={approve.isPending} onClick={() => approve.mutate(r.id)}>
                            <Check /> {t.admin.approve}
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => setRejecting(r)}>
                            <X /> {t.admin.reject}
                          </Button>
                        </div>
                      ) : null}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </CardContent>
      <Dialog
        open={rejecting !== null}
        onOpenChange={(v) => !v && setRejecting(null)}
        title={t.admin.rejectTitle}
        description={rejecting ? `${rejecting.workspace_name} · ${rejecting.amount} ${rejecting.currency}` : undefined}
        footer={
          <Button variant="destructive" disabled={reason.trim().length < 3 || reject.isPending} onClick={() => reject.mutate()}>
            {reject.isPending ? <Spinner /> : null} {t.admin.reject}
          </Button>
        }
      >
        <Field label={t.admin.reason} htmlFor="reject_reason" hint={t.admin.reasonHint}>
          <Textarea id="reject_reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </Dialog>
    </Card>
  );
}

/* ---------------------------------------------------------------- workspaces */

function Workspaces() {
  const { t, locale } = useI18n();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [adjusting, setAdjusting] = useState<AdminWorkspace | null>(null);
  const [delta, setDelta] = useState("");
  const [note, setNote] = useState("");
  const q = useQuery({
    queryKey: ["admin-workspaces", search, page],
    queryFn: () => api<Page<AdminWorkspace>>("/admin/workspaces", { query: { q: search || undefined, page, page_size: 25 } }),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["admin-workspaces"] });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api(`/admin/workspaces/${id}`, { method: "PATCH", body }),
    onSuccess: () => {
      toast.success(t.common.saved);
      refresh();
    },
    onError,
  });
  const adjust = useMutation({
    mutationFn: () => api<{ message: string }>(`/admin/workspaces/${adjusting?.id}/adjust`, { method: "POST", body: { delta: Number(delta), note } }),
    onSuccess: () => {
      toast.success(t.common.saved);
      setAdjusting(null);
      setDelta("");
      setNote("");
      refresh();
    },
    onError,
  });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;
  const deltaValid = /^-?\d+$/.test(delta.trim()) && Number(delta) !== 0;

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <Input
          aria-label={t.admin.search}
          placeholder={t.admin.search}
          className="max-w-sm"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
        />
        {q.isLoading ? (
          <LoadingState rows={4} />
        ) : q.error ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : !q.data?.items.length ? (
          <EmptyState title={t.admin.noWorkspaces} />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <thead>
                <tr>
                  <Th>{t.admin.workspace}</Th>
                  <Th>{t.billing.balance}</Th>
                  <Th>{t.admin.used}</Th>
                  <Th>{t.admin.campaigns}</Th>
                  <Th>{t.billing.plan}</Th>
                  <Th>{t.admin.created}</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((w) => (
                  <tr key={w.id} className={w.suspended_at ? "opacity-60" : undefined}>
                    <Td>
                      <p className="font-medium">{w.name}</p>
                      <p className="text-xs text-muted-foreground">{w.owner_email ?? "—"}</p>
                      {w.suspended_at ? <Badge tone="red" className="mt-1">{t.admin.suspended}</Badge> : null}
                      {w.is_showcase ? <Badge tone="green" className="mt-1">{t.admin.showcase}</Badge> : null}
                    </Td>
                    <Td className="tabular-nums">{w.billing_exempt ? "∞" : formatNumber(w.balance, locale)}</Td>
                    <Td className="tabular-nums">{formatNumber(w.credits_used, locale)}</Td>
                    <Td className="tabular-nums">{w.campaigns}</Td>
                    <Td className="text-xs">
                      {w.billing_exempt ? (
                        <Badge tone="indigo">{t.admin.exempt}</Badge>
                      ) : w.on_trial ? (
                        <span>
                          {t.admin.trialUntil.replace("{date}", formatDate(w.trial_ends_at, locale))}
                        </span>
                      ) : (
                        <Badge tone="green">{t.billing.paidPlan}</Badge>
                      )}
                    </Td>
                    <Td className="whitespace-nowrap text-xs">{formatDate(w.created_at, locale)}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-1.5">
                        <Button size="sm" variant="outline" onClick={() => setAdjusting(w)}>
                          <Plus /> {t.admin.adjust}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => patch.mutate({ id: w.id, body: { billing_exempt: !w.billing_exempt } })}
                        >
                          {w.billing_exempt ? t.admin.meter : t.admin.exemptAction}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          title={t.admin.showcaseHint}
                          onClick={() => patch.mutate({ id: w.id, body: { showcase: !w.is_showcase } })}
                        >
                          {w.is_showcase ? t.admin.unsetShowcase : t.admin.setShowcase}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className={w.suspended_at ? undefined : "text-destructive"}
                          onClick={() => {
                            if (w.suspended_at || window.confirm(t.admin.suspendConfirm.replace("{ws}", w.name))) {
                              patch.mutate({ id: w.id, body: { suspended: !w.suspended_at } });
                            }
                          }}
                        >
                          {w.suspended_at ? <ShieldCheck /> : <ShieldOff />} {w.suspended_at ? t.admin.unsuspend : t.admin.suspend}
                        </Button>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
        {pages > 1 ? (
          <div className="flex items-center justify-end gap-2 text-xs">
            <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t.common.back}</Button>
            <span className="tabular-nums">{page} / {pages}</span>
            <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>{t.billing.next}</Button>
          </div>
        ) : null}
      </CardContent>
      <Dialog
        open={adjusting !== null}
        onOpenChange={(v) => !v && setAdjusting(null)}
        title={t.admin.adjustTitle}
        description={adjusting ? `${adjusting.name} · ${t.billing.balance}: ${adjusting.balance}` : undefined}
        footer={
          <Button disabled={!deltaValid || note.trim().length < 3 || adjust.isPending} onClick={() => adjust.mutate()}>
            {adjust.isPending ? <Spinner /> : null} {t.common.save}
          </Button>
        }
      >
        <Field label={t.admin.delta} htmlFor="adj_delta" hint={t.admin.deltaHint}>
          <Input id="adj_delta" dir="ltr" inputMode="numeric" value={delta} onChange={(e) => setDelta(e.target.value)} />
        </Field>
        <Field label={t.billing.note} htmlFor="adj_note" hint={t.admin.noteHint}>
          <Input id="adj_note" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </Dialog>
    </Card>
  );
}

/* ---------------------------------------------------------------- packages */

const EMPTY_PACKAGE = { name_ar: "", name_en: "", credits: "", price: "", currency: "USD", sort: "0", active: true, featured: false };
type PackageDraft = typeof EMPTY_PACKAGE;

function Packages() {
  const { t, locale } = useI18n();
  const qc = useQueryClient();
  const [editing, setEditing] = useState<{ id: string | null; draft: PackageDraft } | null>(null);
  const q = useQuery({ queryKey: ["admin-packages"], queryFn: () => api<AdminPackage[]>("/admin/packages") });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["admin-packages"] });
    qc.invalidateQueries({ queryKey: ["public-packages"] });
    qc.invalidateQueries({ queryKey: ["billing-packages"] });
  };
  const save = useMutation({
    mutationFn: () => {
      const d = editing!.draft;
      const body = { ...d, credits: Number(d.credits), sort: Number(d.sort || 0), currency: d.currency.toUpperCase() };
      return editing!.id
        ? api(`/admin/packages/${editing!.id}`, { method: "PATCH", body })
        : api("/admin/packages", { method: "POST", body });
    },
    onSuccess: () => {
      toast.success(t.common.saved);
      setEditing(null);
      refresh();
    },
    onError,
  });
  const toggle = useMutation({
    mutationFn: (p: AdminPackage) => api(`/admin/packages/${p.id}`, { method: "PATCH", body: { active: !p.active } }),
    onSuccess: refresh,
    onError,
  });
  const d = editing?.draft;
  const set = (k: keyof PackageDraft, v: string | boolean) => setEditing((e) => (e ? { ...e, draft: { ...e.draft, [k]: v } } : e));
  const valid =
    d && d.name_ar.trim() && d.name_en.trim() && /^\d+$/.test(String(d.credits)) && Number(d.credits) > 0 && /^\d+(\.\d{1,2})?$/.test(String(d.price)) && /^[A-Za-z]{3}$/.test(d.currency);

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <Button size="sm" onClick={() => setEditing({ id: null, draft: EMPTY_PACKAGE })}>
          <Plus /> {t.admin.newPackage}
        </Button>
        {q.isLoading ? (
          <LoadingState rows={3} />
        ) : q.error ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : !q.data?.length ? (
          <EmptyState title={t.admin.noPackages} />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <thead>
                <tr>
                  <Th>{t.admin.name}</Th>
                  <Th>{t.billing.credits}</Th>
                  <Th>{t.admin.price}</Th>
                  <Th>{t.admin.sort}</Th>
                  <Th>{t.admin.active}</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {q.data.map((p) => (
                  <tr key={p.id} className={p.active ? undefined : "opacity-60"}>
                    <Td>
                      <p className="font-medium">{locale === "ar" ? p.name_ar : p.name_en}</p>
                      <p className="text-xs text-muted-foreground">{locale === "ar" ? p.name_en : p.name_ar}</p>
                    </Td>
                    <Td className="tabular-nums">{formatNumber(p.credits, locale)}</Td>
                    <Td className="whitespace-nowrap tabular-nums">{formatPrice(p.price, p.currency)}</Td>
                    <Td className="tabular-nums">
                    {p.sort}
                    {p.featured ? <Badge tone="blue" className="ms-2">{t.admin.featured}</Badge> : null}
                  </Td>
                    <Td>
                      <Switch checked={p.active} onCheckedChange={() => toggle.mutate(p)} aria-label={t.admin.active} />
                    </Td>
                    <Td>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          setEditing({
                            id: p.id,
                            draft: { name_ar: p.name_ar, name_en: p.name_en, credits: String(p.credits), price: p.price, currency: p.currency, sort: String(p.sort), active: p.active, featured: !!p.featured },
                          })
                        }
                      >
                        <Pencil /> {t.admin.edit}
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </CardContent>
      <Dialog
        open={editing !== null}
        onOpenChange={(v) => !v && setEditing(null)}
        title={editing?.id ? t.admin.editPackage : t.admin.newPackage}
        footer={
          <Button disabled={!valid || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? <Spinner /> : null} {t.common.save}
          </Button>
        }
      >
        {d ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t.admin.nameAr} htmlFor="pkg_ar"><Input id="pkg_ar" dir="rtl" value={d.name_ar} onChange={(e) => set("name_ar", e.target.value)} /></Field>
            <Field label={t.admin.nameEn} htmlFor="pkg_en"><Input id="pkg_en" dir="ltr" value={d.name_en} onChange={(e) => set("name_en", e.target.value)} /></Field>
            <Field label={t.billing.credits} htmlFor="pkg_credits"><Input id="pkg_credits" dir="ltr" inputMode="numeric" value={d.credits} onChange={(e) => set("credits", e.target.value)} /></Field>
            <Field label={t.admin.price} htmlFor="pkg_price"><Input id="pkg_price" dir="ltr" inputMode="decimal" value={d.price} onChange={(e) => set("price", e.target.value)} /></Field>
            <Field label={t.admin.currency} htmlFor="pkg_currency"><Input id="pkg_currency" dir="ltr" maxLength={3} value={d.currency} onChange={(e) => set("currency", e.target.value)} /></Field>
            <Field label={t.admin.sort} htmlFor="pkg_sort" hint={t.admin.sortHint}><Input id="pkg_sort" dir="ltr" inputMode="numeric" value={d.sort} onChange={(e) => set("sort", e.target.value)} /></Field>
            <Field label={t.admin.featured} htmlFor="pkg_featured" hint={t.admin.featuredHint}>
              <Switch id="pkg_featured" checked={d.featured} onCheckedChange={(v) => set("featured", v)} />
            </Field>
          </div>
        ) : null}
      </Dialog>
    </Card>
  );
}

/* ---------------------------------------------------------------- contact requests */

function Contacts() {
  const { t, locale } = useI18n();
  const qc = useQueryClient();
  const [status, setStatus] = useState<"new" | "handled" | "">("new");
  const q = useQuery({
    queryKey: ["admin-contacts", status],
    queryFn: () => api<ContactRequest[]>("/admin/contacts", { query: { status: status || undefined } }),
  });
  const handled = useMutation({
    mutationFn: (id: string) => api(`/admin/contacts/${id}/handled`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-contacts"] }),
    onError,
  });
  const interests = t.site.contact.interests as Record<string, string>;
  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <div className="flex flex-wrap gap-2">
          {(["new", "handled", ""] as const).map((s) => (
            <Button key={s || "all"} size="sm" variant={status === s ? "default" : "outline"} onClick={() => setStatus(s)}>
              {s === "new" ? t.admin.new : s === "handled" ? t.admin.handled : t.admin.all}
            </Button>
          ))}
        </div>
        {q.isLoading ? (
          <LoadingState rows={3} />
        ) : q.error ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : !q.data?.length ? (
          <EmptyState title={t.admin.noContacts} />
        ) : (
          <ul className="space-y-3">
            {q.data.map((c) => (
              <li key={c.id} className="rounded-lg border p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-medium">
                      {c.name}
                      {c.company ? <span className="text-muted-foreground"> · {c.company}</span> : null}
                    </p>
                    <p className="mt-0.5 text-sm" dir="ltr">
                      <a href={`mailto:${c.email}`} className="text-primary hover:underline">{c.email}</a>
                      {c.phone ? <span className="text-muted-foreground"> · {c.phone}</span> : null}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone="blue">{interests[c.interest] ?? c.interest}</Badge>
                    <span className="text-xs text-muted-foreground">{formatDate(c.created_at, locale)}</span>
                  </div>
                </div>
                {c.message ? <p className="mt-3 whitespace-pre-line text-sm">{c.message}</p> : null}
                {c.status === "new" ? (
                  <Button size="sm" variant="outline" className="mt-3" disabled={handled.isPending} onClick={() => handled.mutate(c.id)}>
                    <Check /> {t.admin.markHandled}
                  </Button>
                ) : (
                  <Badge tone="green" className="mt-3">{t.admin.handled}</Badge>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/* ---------------------------------------------------------------- platform settings */

function SettingsForm() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin-settings"], queryFn: () => api<PlatformSettings>("/admin/settings") });
  if (q.isLoading) return <LoadingState rows={3} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  return <SettingsEditor initial={q.data} onSaved={() => qc.invalidateQueries({ queryKey: ["admin-settings"] })} />;
}

function SettingsEditor({ initial, onSaved }: { initial: PlatformSettings; onSaved: () => void }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [s, setS] = useState({ ...initial, trial_days: String(initial.trial_days), trial_credits: String(initial.trial_credits), credits_per_contact: String(initial.credits_per_contact) });
  const save = useMutation({
    mutationFn: () =>
      api("/admin/settings", {
        method: "PUT",
        body: { ...s, trial_days: Number(s.trial_days), trial_credits: Number(s.trial_credits), credits_per_contact: Number(s.credits_per_contact) },
      }),
    onSuccess: () => {
      toast.success(t.common.saved);
      qc.invalidateQueries({ queryKey: ["public-trial"] });
      qc.invalidateQueries({ queryKey: ["billing-summary"] });
      onSaved();
    },
    onError,
  });
  const int = (v: string) => /^\d+$/.test(v.trim());
  const valid =
    int(s.trial_days) && int(s.trial_credits) && int(s.credits_per_contact) && Number(s.credits_per_contact) >= 1 &&
    researchDefaultsValid(s.research_defaults);
  return (
    <div className="space-y-6">
    <ResearchDefaultsEditor value={s.research_defaults} onChange={(research_defaults) => setS({ ...s, research_defaults })} />
    <Card>
      <CardContent className="space-y-5 p-5">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t.admin.trialDays} htmlFor="st_days">
            <Input id="st_days" dir="ltr" inputMode="numeric" value={s.trial_days} onChange={(e) => setS({ ...s, trial_days: e.target.value })} />
          </Field>
          <Field label={t.admin.trialCredits} htmlFor="st_credits">
            <Input id="st_credits" dir="ltr" inputMode="numeric" value={s.trial_credits} onChange={(e) => setS({ ...s, trial_credits: e.target.value })} />
          </Field>
          <Field label={t.admin.creditsPerContact} htmlFor="st_per">
            <Input id="st_per" dir="ltr" inputMode="numeric" value={s.credits_per_contact} onChange={(e) => setS({ ...s, credits_per_contact: e.target.value })} />
          </Field>
        </div>
        <p className="text-xs text-muted-foreground">{t.admin.settingsHint}</p>
        <Field label={t.admin.signupReview} htmlFor="st_review" hint={t.admin.signupReviewHint}>
          <Switch id="st_review" checked={s.signup_review} onCheckedChange={(v) => setS({ ...s, signup_review: v })} />
        </Field>
        <Button disabled={!valid || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? <Spinner /> : null} {t.common.save}
        </Button>
      </CardContent>
    </Card>
    </div>
  );
}
