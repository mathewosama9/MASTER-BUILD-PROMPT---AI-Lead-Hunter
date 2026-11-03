"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ExternalLink,
  Gift,
  KeyRound,
  Laptop,
  Minus,
  Plus,
  RotateCcw,
  Save,
  Send,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Smartphone,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Badge,
  type BadgeTone,
  Dialog,
  Field,
  Input,
  Select,
  Switch,
  Table,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Td,
  Textarea,
  Th,
} from "@/components/ui/primitives";
import { ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api, API_BASE } from "@/lib/api";
import { countryFlag, countryName, countryOptions } from "@/lib/countries";
import { cn, formatDate, formatNumber, formatPrice, relativeTime } from "@/lib/utils";
import type { CreditPackage, TopUp } from "@/types/api";

import { ViewAsButton } from "./ops";

export type Approval = "pending" | "approved" | "rejected";
export type Signal = "device" | "fingerprint" | "phone" | "email" | "ip";
export type TelegramState = "linked" | "pending" | "none";

export interface WorkspaceBrief {
  id: string;
  name: string;
  role: string;
  balance: number;
  billing_exempt: boolean;
  trial_ends_at: string | null;
  on_trial: boolean;
  suspended_at: string | null;
}
export interface UserRow {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  nationality: string | null;
  approval_status: Approval;
  is_active: boolean;
  is_superuser: boolean;
  email_verified_at: string | null;
  created_at: string;
  last_login_at: string | null;
  last_seen_at: string | null;
  signup_ip: string | null;
  matches: number;
  strong_matches: number;
  workspace: WorkspaceBrief | null;
  telegram_status: TelegramState;
  telegram_username: string | null;
}
interface WorkspaceDetail extends WorkspaceBrief {
  campaigns: number;
  credits_used: number;
  credits_purchased: number;
  paid: Record<string, string>;
}
interface Duplicate {
  user_id: string;
  email: string;
  full_name: string;
  approval_status: Approval;
  is_active: boolean;
  created_at: string;
  kinds: Signal[];
  values: Partial<Record<Signal, string>>;
  strong: boolean;
}
interface Device {
  id: string;
  user_agent: string | null;
  ip: string | null;
  first_seen: string;
  last_seen: string | null;
  shared_with: number;
}
interface UserDetail extends UserRow {
  locale: string;
  last_seen_ip: string | null;
  admin_notes: string | null;
  suspicion: "strong" | "weak" | "none";
  devices: Device[];
  reviewed_at: string | null;
  reviewed_by: string | null;
  review_note: string | null;
  workspaces: WorkspaceDetail[];
  duplicates: Duplicate[];
  topups: (TopUp & { workspace_id: string })[];
  transactions: { id: string; delta: number; balance_after: number; kind: string; note: string | null; created_at: string }[];
  logins: { at: string; action: string; ip: string | null; via: string }[];
}

export const APPROVAL_TONE: Record<Approval, BadgeTone> = { pending: "yellow", approved: "green", rejected: "red" };
const STRONG: Signal[] = ["device", "phone", "email"];
const TELEGRAM_TONE: Record<TelegramState, BadgeTone> = { linked: "green", pending: "yellow", none: "neutral" };
const MANUAL_METHODS = ["cash", "bank_transfer", "instapay", "vodafone_cash"] as const;
const onError = (e: Error) => toast.error(e.message);

/** "Chrome · Windows" from a user-agent string; good enough to tell a user's devices apart. */
export function describeAgent(ua: string | null): { label: string; mobile: boolean } {
  if (!ua) return { label: "—", mobile: false };
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /OPR\/|Opera/.test(ua)
      ? "Opera"
      : /SamsungBrowser/.test(ua)
        ? "Samsung Internet"
        : /Chrome\//.test(ua)
          ? "Chrome"
          : /Firefox\//.test(ua)
            ? "Firefox"
            : /Safari\//.test(ua)
              ? "Safari"
              : "Browser";
  const os = /iPhone|iPad/.test(ua)
    ? "iOS"
    : /Android/.test(ua)
      ? "Android"
      : /Windows/.test(ua)
        ? "Windows"
        : /Mac OS X/.test(ua)
          ? "macOS"
          : /Linux/.test(ua)
            ? "Linux"
            : "";
  return { label: os ? `${browser} · ${os}` : browser, mobile: /Mobile|Android|iPhone/.test(ua) };
}

export function TelegramBadge({ state, username }: { state: TelegramState; username: string | null }) {
  const u = useI18n().t.admin.users;
  const text = state === "linked" ? (username ? `@${username}` : u.tgLinked) : state === "pending" ? u.tgPending : u.tgNone;
  return (
    <Badge tone={TELEGRAM_TONE[state]} className="whitespace-nowrap">
      <Send className="size-3" aria-hidden /> <span dir={state === "linked" && username ? "ltr" : undefined}>{text}</span>
    </Badge>
  );
}

export function PlanBadge({ w }: { w: WorkspaceBrief }) {
  const { t, locale } = useI18n();
  if (w.suspended_at) return <Badge tone="red" className="mt-1">{t.admin.suspended}</Badge>;
  if (w.billing_exempt) return <Badge tone="indigo" className="mt-1">{t.admin.exempt}</Badge>;
  if (w.on_trial) return <span className="mt-1 block text-[11px] text-muted-foreground">{t.admin.trialUntil.replace("{date}", formatDate(w.trial_ends_at, locale))}</span>;
  if (w.trial_ends_at) return <Badge tone="green" className="mt-1">{t.billing.paidPlan}</Badge>;
  return <span className="mt-1 block text-[11px] text-muted-foreground">{t.admin.users.noTrialYet}</span>;
}

/** "5 minutes ago" for recent activity, a date after a week. */
function seenText(at: string, locale: string) {
  const recent = Date.now() - new Date(at).getTime() < 7 * 86_400_000;
  return recent ? relativeTime(at, locale) : formatDate(at, locale);
}

export function LastSeen({ at }: { at: string | null }) {
  const { locale } = useI18n();
  if (!at) return <>—</>;
  return <span title={formatDate(at, locale)}>{seenText(at, locale)}</span>;
}

export function UserDialog({ id, onOpen, onClose }: { id: string; onOpen: (id: string) => void; onClose: () => void }) {
  const { t } = useI18n();
  const u = t.admin.users;
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin-user", id], queryFn: () => api<UserDetail>(`/admin/users/${id}`) });
  const refresh = (d?: UserDetail) => {
    if (d) qc.setQueryData(["admin-user", id], d);
    else qc.invalidateQueries({ queryKey: ["admin-user", id] });
    qc.invalidateQueries({ queryKey: ["admin-users"] });
    qc.invalidateQueries({ queryKey: ["admin-users-summary"] });
    qc.invalidateQueries({ queryKey: ["admin-workspaces"] });
    qc.invalidateQueries({ queryKey: ["admin-topups"] });
  };
  const d = q.data;

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()} title={d ? d.full_name || d.email : u.details} description={d?.email} wide>
      {q.isLoading ? (
        <LoadingState rows={6} />
      ) : q.error || !d ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <div className="space-y-4">
          <Header d={d} onDone={refresh} />
          <Tabs defaultValue={d.approval_status === "pending" && d.duplicates.length ? "duplicates" : "profile"}>
            <TabsList className="h-auto">
              <TabsTrigger value="profile">{u.tabProfile}</TabsTrigger>
              <TabsTrigger value="billing">{u.tabBilling}</TabsTrigger>
              <TabsTrigger value="activity">{u.tabActivity}</TabsTrigger>
              <TabsTrigger value="duplicates">
                {u.tabDuplicates}
                {d.duplicates.length ? <Badge tone={d.suspicion === "strong" ? "red" : "yellow"}>{d.duplicates.length}</Badge> : null}
              </TabsTrigger>
            </TabsList>
            <TabsContent value="profile">
              <ProfileTab d={d} onDone={refresh} />
            </TabsContent>
            <TabsContent value="billing">
              <BillingTab d={d} onDone={refresh} />
            </TabsContent>
            <TabsContent value="activity">
              <ActivityTab d={d} />
            </TabsContent>
            <TabsContent value="duplicates">
              <DuplicatesTab d={d} onOpen={onOpen} />
            </TabsContent>
          </Tabs>
        </div>
      )}
    </Dialog>
  );
}

/* ---------------------------------------------------------------- header: status and review actions */

function Header({ d, onDone }: { d: UserDetail; onDone: (d?: UserDetail) => void }) {
  const { t, locale } = useI18n();
  const u = t.admin.users;
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const approve = useMutation({
    mutationFn: () => api<UserDetail>(`/admin/users/${d.id}/approve`, { method: "POST" }),
    onSuccess: (r) => {
      toast.success(u.approvedToast);
      onDone(r);
    },
    onError,
  });
  const reject = useMutation({
    mutationFn: () => api<UserDetail>(`/admin/users/${d.id}/reject`, { method: "POST", body: { reason } }),
    onSuccess: (r) => {
      toast.success(u.rejectedToast);
      setRejecting(false);
      setReason("");
      onDone(r);
    },
    onError,
  });
  const suspicionTone: BadgeTone = d.suspicion === "strong" ? "red" : d.suspicion === "weak" ? "yellow" : "green";

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 rounded-lg border p-3">
        <Badge tone={APPROVAL_TONE[d.approval_status]} className="text-xs">{u.status[d.approval_status]}</Badge>
        <Badge tone={suspicionTone} className="text-xs">
          {d.suspicion === "none" ? <ShieldCheck className="size-3" aria-hidden /> : <ShieldAlert className="size-3" aria-hidden />}
          {u.suspicionLevel[d.suspicion]}
        </Badge>
        {!d.is_active ? <Badge tone="red" className="text-xs">{u.deactivated}</Badge> : null}
        {d.is_superuser ? <Badge tone="indigo">{u.superuser}</Badge> : null}
        <span className="text-xs text-muted-foreground">
          {u.lastSeen}: <LastSeen at={d.last_seen_at} />
        </span>
        <span className="text-xs text-muted-foreground">
          {d.nationality ? `${countryFlag(d.nationality)} ${countryName(d.nationality, locale)}` : null}
        </span>
        <div className="ms-auto flex flex-wrap gap-2">
          {!d.is_superuser && d.is_active && d.workspaces.length ? <ViewAsButton userId={d.id} /> : null}
          {d.approval_status !== "approved" ? (
            <Button size="sm" disabled={approve.isPending} onClick={() => approve.mutate()}>
              {approve.isPending ? <Spinner /> : d.approval_status === "rejected" ? <RotateCcw /> : <Check />}
              {d.approval_status === "rejected" ? u.readmit : u.approve}
            </Button>
          ) : null}
          {d.approval_status !== "rejected" && !d.is_superuser ? (
            <Button size="sm" variant="outline" className="text-destructive" onClick={() => setRejecting((v) => !v)}>
              <X /> {u.reject}
            </Button>
          ) : null}
        </div>
      </div>
      {rejecting ? (
        <div className="space-y-3 rounded-lg border border-destructive/40 p-4">
          <Field label={u.rejectTitle} htmlFor="reject_user_reason" hint={u.rejectHint}>
            <Textarea id="reject_user_reason" rows={2} value={reason} placeholder={u.reasonPlaceholder} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <div className="flex flex-wrap gap-2">
            {[u.reasonDuplicate, u.reasonFake].map((r) => (
              <Button key={r} size="sm" variant="outline" onClick={() => setReason(r)}>{r}</Button>
            ))}
            <Button size="sm" variant="destructive" className="ms-auto" disabled={reason.trim().length < 3 || reject.isPending} onClick={() => reject.mutate()}>
              {reject.isPending ? <Spinner /> : null} {u.reject}
            </Button>
          </div>
        </div>
      ) : null}
      {d.review_note && d.approval_status === "rejected" ? (
        <p className="text-xs text-muted-foreground">
          {u.reviewNote}: {d.review_note} · {d.reviewed_by ?? "—"} · {formatDate(d.reviewed_at, locale)}
        </p>
      ) : null}
    </>
  );
}

/* ---------------------------------------------------------------- profile: editable fields */

function ProfileTab({ d, onDone }: { d: UserDetail; onDone: (d?: UserDetail) => void }) {
  const { t, locale } = useI18n();
  const u = t.admin.users;
  const countries = useMemo(() => countryOptions(locale), [locale]);
  const initial = {
    full_name: d.full_name,
    email: d.email,
    phone: d.phone ?? "",
    nationality: d.nationality ?? "",
    locale: d.locale === "ar" ? "ar" : "en",
    admin_notes: d.admin_notes ?? "",
  };
  const [f, setF] = useState(initial);
  const dirty = (Object.keys(initial) as (keyof typeof initial)[]).filter((k) => f[k] !== initial[k]);
  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<UserDetail>(`/admin/users/${d.id}`, { method: "PATCH", body }),
    onSuccess: (r) => {
      toast.success(t.common.saved);
      setF({
        full_name: r.full_name,
        email: r.email,
        phone: r.phone ?? "",
        nationality: r.nationality ?? "",
        locale: r.locale === "ar" ? "ar" : "en",
        admin_notes: r.admin_notes ?? "",
      });
      onDone(r);
    },
    onError,
  });
  const reset = useMutation({
    mutationFn: () => api(`/admin/users/${d.id}/password-reset`, { method: "POST" }),
    onSuccess: () => toast.success(u.resetSent),
    onError,
  });
  const set = (k: keyof typeof initial, v: string) => setF((x) => ({ ...x, [k]: v }));

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={u.name} htmlFor="ue_name">
          <Input id="ue_name" value={f.full_name} onChange={(e) => set("full_name", e.target.value)} />
        </Field>
        <Field label={u.email} htmlFor="ue_email" hint={f.email !== initial.email ? u.emailChangeHint : undefined}>
          <Input id="ue_email" dir="ltr" type="email" value={f.email} onChange={(e) => set("email", e.target.value)} />
        </Field>
        <Field label={u.phone} htmlFor="ue_phone">
          <Input id="ue_phone" dir="ltr" value={f.phone} onChange={(e) => set("phone", e.target.value)} />
        </Field>
        <Field label={u.nationality} htmlFor="ue_nat">
          <Select id="ue_nat" value={f.nationality} onChange={(e) => set("nationality", e.target.value)}>
            <option value="">—</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>{c.name}</option>
            ))}
          </Select>
        </Field>
        <Field label={u.language} htmlFor="ue_locale">
          <Select id="ue_locale" value={f.locale} onChange={(e) => set("locale", e.target.value)}>
            <option value="ar">العربية</option>
            <option value="en">English</option>
          </Select>
        </Field>
        <div className="grid gap-3 rounded-lg border p-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span>
              {u.emailStatus}: {d.email_verified_at ? `${u.verified} · ${formatDate(d.email_verified_at, locale)}` : u.notVerified}
            </span>
            <Switch
              checked={!!d.email_verified_at}
              aria-label={u.markVerified}
              onCheckedChange={(v) => patch.mutate({ email_verified: v })}
            />
          </div>
          <div className="flex items-center justify-between gap-3">
            <span>{d.is_active ? u.active : u.deactivated}</span>
            <Switch
              checked={d.is_active}
              disabled={d.is_superuser}
              aria-label={u.active}
              onCheckedChange={(v) => {
                if (v || window.confirm(u.deactivateConfirm)) patch.mutate({ is_active: v });
              }}
            />
          </div>
        </div>
      </div>
      <Field label={u.adminNotes} htmlFor="ue_notes" hint={u.adminNotesHint}>
        <Textarea id="ue_notes" rows={3} value={f.admin_notes} onChange={(e) => set("admin_notes", e.target.value)} />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={!dirty.length || patch.isPending}
          onClick={() => patch.mutate(Object.fromEntries(dirty.map((k) => [k, k === "admin_notes" ? f[k] : f[k] || undefined])))}
        >
          {patch.isPending ? <Spinner /> : <Save />} {t.common.save}
        </Button>
        <Button variant="outline" disabled={reset.isPending} onClick={() => reset.mutate()}>
          {reset.isPending ? <Spinner /> : <KeyRound />} {u.sendReset}
        </Button>
      </div>
      <dl className="grid gap-x-6 gap-y-3 border-t pt-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <Item k={u.telegram} v={<TelegramBadge state={d.telegram_status} username={d.telegram_username} />} />
        <Item k={u.created} v={formatDate(d.created_at, locale)} />
        <Item k={u.signupIp} v={<span dir="ltr" className="font-mono text-xs">{d.signup_ip ?? "—"}</span>} />
        {d.reviewed_at ? <Item k={u.reviewed} v={`${d.reviewed_by ?? "—"} · ${formatDate(d.reviewed_at, locale)}`} /> : null}
      </dl>
    </div>
  );
}

/* ---------------------------------------------------------------- subscription, credits and payments */

function BillingTab({ d, onDone }: { d: UserDetail; onDone: (d?: UserDetail) => void }) {
  const { t, locale, label } = useI18n();
  const u = t.admin.users;
  const [rejectingTopup, setRejectingTopup] = useState<string | null>(null);
  const [topupReason, setTopupReason] = useState("");
  const approveTopup = useMutation({
    mutationFn: (topupId: string) => api(`/admin/topups/${topupId}/approve`, { method: "POST" }),
    onSuccess: () => {
      toast.success(u.paymentApproved);
      onDone();
    },
    onError,
  });
  const rejectTopup = useMutation({
    mutationFn: () => api(`/admin/topups/${rejectingTopup}/reject`, { method: "POST", body: { reason: topupReason } }),
    onSuccess: () => {
      toast.success(t.admin.rejected);
      setRejectingTopup(null);
      setTopupReason("");
      onDone();
    },
    onError,
  });

  return (
    <div className="space-y-6">
      {!d.workspaces.length ? <p className="text-sm text-muted-foreground">—</p> : null}
      {d.workspaces.map((w) => (
        <WorkspaceControls key={w.id} userId={d.id} w={w} onDone={onDone} />
      ))}

      <Section title={u.payments}>
        {!d.topups.length ? (
          <p className="text-sm text-muted-foreground">{u.noPayments}</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <thead>
                <tr>
                  <Th>{t.billing.date}</Th>
                  <Th>{t.billing.credits}</Th>
                  <Th>{t.billing.amount}</Th>
                  <Th>{t.billing.method}</Th>
                  <Th>{t.billing.reference}</Th>
                  <Th>{t.billing.status}</Th>
                  <Th>{t.billing.receipt}</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {d.topups.map((p) => (
                  <tr key={p.id}>
                    <Td className="whitespace-nowrap text-xs">{formatDate(p.created_at, locale)}</Td>
                    <Td className="tabular-nums">{formatNumber(p.credits, locale)}</Td>
                    <Td className="whitespace-nowrap tabular-nums">{formatPrice(p.amount, p.currency)}</Td>
                    <Td>{label(p.method)}</Td>
                    <Td className="font-mono text-xs" dir="ltr">{p.reference ?? "—"}</Td>
                    <Td>
                      <Badge tone={p.status === "approved" ? "green" : p.status === "rejected" ? "red" : "yellow"}>{label(p.status)}</Badge>
                      {p.reason ? <p className="mt-1 max-w-40 text-[11px] text-muted-foreground">{p.reason}</p> : null}
                    </Td>
                    <Td>
                      {p.receipt_filename ? (
                        <a href={`${API_BASE}/admin/topups/${p.id}/receipt`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
                          {t.billing.view} <ExternalLink className="size-3" aria-hidden />
                        </a>
                      ) : (
                        "—"
                      )}
                    </Td>
                    <Td>
                      {p.status === "pending" && p.method !== "paypal" ? (
                        <div className="flex gap-1">
                          <Button size="sm" disabled={approveTopup.isPending} onClick={() => approveTopup.mutate(p.id)}>
                            <Check /> {t.admin.approve}
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => setRejectingTopup(p.id)}>
                            <X />
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
        {rejectingTopup ? (
          <div className="mt-3 flex flex-wrap items-end gap-2 rounded-lg border border-destructive/40 p-3">
            <Field label={t.admin.reason} htmlFor="topup_reason" hint={t.admin.reasonHint}>
              <Input id="topup_reason" className="w-72" value={topupReason} onChange={(e) => setTopupReason(e.target.value)} />
            </Field>
            <Button size="sm" variant="destructive" disabled={topupReason.trim().length < 3 || rejectTopup.isPending} onClick={() => rejectTopup.mutate()}>
              {t.admin.reject}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setRejectingTopup(null)}>{t.common.cancel}</Button>
          </div>
        ) : null}
      </Section>

      <Section title={u.creditHistory}>
        {!d.transactions.length ? (
          <p className="text-sm text-muted-foreground">{u.noCredits}</p>
        ) : (
          <div className="max-h-72 overflow-auto">
            <Table>
              <thead>
                <tr>
                  <Th>{t.billing.date}</Th>
                  <Th>{u.kind}</Th>
                  <Th>{t.billing.credits}</Th>
                  <Th>{t.billing.balance}</Th>
                  <Th>{t.billing.note}</Th>
                </tr>
              </thead>
              <tbody>
                {d.transactions.map((x) => (
                  <tr key={x.id}>
                    <Td className="whitespace-nowrap text-xs">{formatDate(x.created_at, locale)}</Td>
                    <Td>{label(x.kind)}</Td>
                    <Td className={cn("tabular-nums", x.delta > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400")} dir="ltr">
                      {x.delta > 0 ? `+${x.delta}` : x.delta}
                    </Td>
                    <Td className="tabular-nums">{formatNumber(x.balance_after, locale)}</Td>
                    <Td className="max-w-64 truncate text-xs text-muted-foreground">{x.note ?? "—"}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </Section>
    </div>
  );
}

type Panel = "credits" | "package" | "trial" | null;

function WorkspaceControls({ userId, w, onDone }: { userId: string; w: WorkspaceDetail; onDone: (d?: UserDetail) => void }) {
  const { t, locale, label } = useI18n();
  const u = t.admin.users;
  const [panel, setPanel] = useState<Panel>(null);
  const [delta, setDelta] = useState("");
  const [sign, setSign] = useState<1 | -1>(1);
  const [note, setNote] = useState("");
  const [grant, setGrant] = useState({ package_id: "", method: "cash", amount: "", reference: "", note: "" });
  // One id per grant attempt: a double click or a retried request grants the package once.
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [trialEnd, setTrialEnd] = useState(w.trial_ends_at ? w.trial_ends_at.slice(0, 10) : "");
  const packages = useQuery({ queryKey: ["admin-packages"], queryFn: () => api<(CreditPackage & { active: boolean })[]>("/admin/packages"), enabled: panel === "package" });
  const close = () => {
    setPanel(null);
    setDelta("");
    setNote("");
  };
  const adjust = useMutation({
    mutationFn: () => api(`/admin/workspaces/${w.id}/adjust`, { method: "POST", body: { delta: sign * Number(delta), note } }),
    onSuccess: () => {
      toast.success(t.common.saved);
      close();
      onDone();
    },
    onError,
  });
  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api(`/admin/workspaces/${w.id}`, { method: "PATCH", body }),
    onSuccess: () => {
      toast.success(t.common.saved);
      close();
      onDone();
    },
    onError,
  });
  const give = useMutation({
    mutationFn: () =>
      api<UserDetail>(`/admin/users/${userId}/grant-package`, {
        method: "POST",
        body: {
          workspace_id: w.id,
          package_id: grant.package_id,
          method: grant.method,
          amount: grant.amount.trim() === "" ? undefined : grant.amount.trim(),
          reference: grant.reference.trim() || undefined,
          note: grant.note.trim() || undefined,
          request_id: requestId,
        },
      }),
    onSuccess: (r) => {
      toast.success(u.packageGranted);
      setGrant({ package_id: "", method: "cash", amount: "", reference: "", note: "" });
      setRequestId(crypto.randomUUID());
      setPanel(null);
      onDone(r);
    },
    onError,
  });
  const chosen = packages.data?.find((p) => p.id === grant.package_id);
  const deltaValid = /^\d+$/.test(delta.trim()) && Number(delta) > 0;
  const amountValid = grant.amount.trim() === "" || /^\d+(\.\d{1,2})?$/.test(grant.amount.trim());
  const extend = (days: number) => {
    const base = w.trial_ends_at && new Date(w.trial_ends_at) > new Date() ? new Date(w.trial_ends_at) : new Date();
    base.setDate(base.getDate() + days);
    patch.mutate({ trial_ends_at: base.toISOString() });
  };

  return (
    <section className="rounded-lg border">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b p-4">
        <div>
          <p className="font-medium">
            {w.name} <Badge className="ms-1">{label(w.role)}</Badge>
          </p>
          <PlanBadge w={w} />
        </div>
        <div className="text-end">
          <p className="text-xs text-muted-foreground">{t.billing.balance}</p>
          <p className="text-2xl font-semibold tabular-nums">{w.billing_exempt ? "∞" : formatNumber(w.balance, locale)}</p>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-3 p-4 text-sm sm:grid-cols-4">
        <Item k={t.admin.campaigns} v={formatNumber(w.campaigns, locale)} />
        <Item k={t.admin.used} v={formatNumber(w.credits_used, locale)} />
        <Item k={u.purchased} v={formatNumber(w.credits_purchased, locale)} />
        <Item k={u.paid} v={Object.keys(w.paid).length ? Object.entries(w.paid).map(([c, a]) => formatPrice(a, c)).join(" + ") : "—"} />
      </dl>
      <div className="flex flex-wrap gap-2 border-t p-4">
        <Button size="sm" variant={panel === "credits" ? "default" : "outline"} onClick={() => setPanel(panel === "credits" ? null : "credits")}>
          <Plus /> {u.editCredits}
        </Button>
        <Button size="sm" variant={panel === "package" ? "default" : "outline"} onClick={() => setPanel(panel === "package" ? null : "package")}>
          <Gift /> {u.grantPackage}
        </Button>
        <Button size="sm" variant={panel === "trial" ? "default" : "outline"} onClick={() => setPanel(panel === "trial" ? null : "trial")}>
          {u.editTrial}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => patch.mutate({ billing_exempt: !w.billing_exempt })}>
          {w.billing_exempt ? t.admin.meter : t.admin.exemptAction}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className={w.suspended_at ? undefined : "text-destructive"}
          onClick={() => {
            if (w.suspended_at || window.confirm(t.admin.suspendConfirm.replace("{ws}", w.name))) patch.mutate({ suspended: !w.suspended_at });
          }}
        >
          {w.suspended_at ? <ShieldCheck /> : <ShieldOff />} {w.suspended_at ? t.admin.unsuspend : t.admin.suspend}
        </Button>
      </div>

      {panel === "credits" ? (
        <div className="grid gap-3 border-t bg-muted/30 p-4 sm:grid-cols-[auto_8rem_1fr_auto] sm:items-end">
          <div className="flex gap-1" role="group" aria-label={t.admin.delta}>
            <Button size="sm" variant={sign === 1 ? "default" : "outline"} onClick={() => setSign(1)} aria-pressed={sign === 1}>
              <Plus /> {u.add}
            </Button>
            <Button size="sm" variant={sign === -1 ? "default" : "outline"} onClick={() => setSign(-1)} aria-pressed={sign === -1}>
              <Minus /> {u.remove}
            </Button>
          </div>
          <Field label={t.billing.credits} htmlFor={`adj_${w.id}`}>
            <Input id={`adj_${w.id}`} dir="ltr" inputMode="numeric" value={delta} onChange={(e) => setDelta(e.target.value)} />
          </Field>
          <Field label={t.billing.note} htmlFor={`adjn_${w.id}`} hint={t.admin.noteHint}>
            <Input id={`adjn_${w.id}`} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <Button disabled={!deltaValid || note.trim().length < 3 || adjust.isPending} onClick={() => adjust.mutate()}>
            {adjust.isPending ? <Spinner /> : null} {t.common.save}
          </Button>
        </div>
      ) : null}

      {panel === "package" ? (
        <div className="space-y-3 border-t bg-muted/30 p-4">
          <p className="text-xs text-muted-foreground">{u.grantHint}</p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label={u.package} htmlFor={`gp_${w.id}`}>
              <Select id={`gp_${w.id}`} value={grant.package_id} onChange={(e) => setGrant({ ...grant, package_id: e.target.value })}>
                <option value="">—</option>
                {(packages.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {(locale === "ar" ? p.name_ar : p.name_en) + ` · ${formatNumber(p.credits, locale)} · ${formatPrice(p.price, p.currency)}`}
                    {p.active ? "" : ` (${u.inactive})`}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t.billing.method} htmlFor={`gm_${w.id}`}>
              <Select id={`gm_${w.id}`} value={grant.method} onChange={(e) => setGrant({ ...grant, method: e.target.value })}>
                {MANUAL_METHODS.map((m) => (
                  <option key={m} value={m}>{label(m)}</option>
                ))}
              </Select>
            </Field>
            <Field label={t.billing.amount} htmlFor={`ga_${w.id}`} hint={chosen ? u.amountHint.replace("{price}", formatPrice(chosen.price, chosen.currency)) : u.giftHint}>
              <Input id={`ga_${w.id}`} dir="ltr" inputMode="decimal" placeholder={chosen ? String(chosen.price) : ""} value={grant.amount} onChange={(e) => setGrant({ ...grant, amount: e.target.value })} />
            </Field>
            <Field label={t.billing.reference} htmlFor={`gr_${w.id}`}>
              <Input id={`gr_${w.id}`} dir="ltr" value={grant.reference} onChange={(e) => setGrant({ ...grant, reference: e.target.value })} />
            </Field>
          </div>
          <Field label={t.billing.note} htmlFor={`gn_${w.id}`}>
            <Input id={`gn_${w.id}`} value={grant.note} onChange={(e) => setGrant({ ...grant, note: e.target.value })} />
          </Field>
          <Button disabled={!grant.package_id || !amountValid || give.isPending} onClick={() => give.mutate()}>
            {give.isPending ? <Spinner /> : <Gift />} {u.grantPackage}
          </Button>
        </div>
      ) : null}

      {panel === "trial" ? (
        <div className="flex flex-wrap items-end gap-3 border-t bg-muted/30 p-4">
          <Field label={u.trialEnd} htmlFor={`te_${w.id}`}>
            <Input id={`te_${w.id}`} type="date" dir="ltr" value={trialEnd} onChange={(e) => setTrialEnd(e.target.value)} />
          </Field>
          <Button disabled={!trialEnd || patch.isPending} onClick={() => patch.mutate({ trial_ends_at: new Date(`${trialEnd}T23:59:00`).toISOString() })}>
            {t.common.save}
          </Button>
          {[7, 14, 30].map((n) => (
            <Button key={n} size="sm" variant="outline" disabled={patch.isPending} onClick={() => extend(n)}>
              +{n} {u.days}
            </Button>
          ))}
          <Button size="sm" variant="ghost" className="text-destructive" disabled={patch.isPending} onClick={() => patch.mutate({ trial_ends_at: new Date().toISOString() })}>
            {u.endTrialNow}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

/* ---------------------------------------------------------------- activity: last seen, devices, sign-ins */

function ActivityTab({ d }: { d: UserDetail }) {
  const { t, locale } = useI18n();
  const u = t.admin.users;
  return (
    <div className="space-y-6">
      <dl className="grid gap-x-6 gap-y-3 rounded-lg border p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <Item k={u.lastSeen} v={<LastSeen at={d.last_seen_at} />} />
        <Item k={u.lastSeenIp} v={<span dir="ltr" className="font-mono text-xs">{d.last_seen_ip ?? "—"}</span>} />
        <Item k={u.lastLogin} v={formatDate(d.last_login_at, locale)} />
        <Item k={u.devicesCount} v={formatNumber(d.devices.length, locale)} />
      </dl>

      <Section title={u.devices}>
        {!d.devices.length ? (
          <p className="text-sm text-muted-foreground">{u.noDevices}</p>
        ) : (
          <ul className="grid gap-2 md:grid-cols-2">
            {d.devices.map((dev) => {
              const a = describeAgent(dev.user_agent);
              const Icon = a.mobile ? Smartphone : Laptop;
              return (
                <li key={dev.id} className={cn("rounded-lg border p-3", dev.shared_with && "border-destructive/40 bg-destructive/5")}>
                  <div className="flex items-center gap-2">
                    <Icon className="size-4 text-muted-foreground" aria-hidden />
                    <p className="font-medium">{a.label}</p>
                    <span className="ms-auto font-mono text-[11px] text-muted-foreground" dir="ltr">#{dev.id}</span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {u.lastSeen}: <LastSeen at={dev.last_seen} /> · {u.firstSeen}: {formatDate(dev.first_seen, locale)}
                  </p>
                  <p className="text-xs text-muted-foreground" dir="ltr">{dev.ip ?? "—"}</p>
                  {dev.shared_with ? (
                    <Badge tone="red" className="mt-2">
                      <ShieldAlert className="size-3" aria-hidden /> {u.sharedDevice.replace("{n}", String(dev.shared_with))}
                    </Badge>
                  ) : null}
                  {dev.user_agent ? <p className="mt-1 truncate text-[10px] text-muted-foreground" dir="ltr" title={dev.user_agent}>{dev.user_agent}</p> : null}
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <Section title={u.logins}>
        {!d.logins.length ? (
          <p className="text-sm text-muted-foreground">—</p>
        ) : (
          <ul className="divide-y text-sm">
            {d.logins.map((l, i) => (
              <li key={i} className="flex flex-wrap items-center gap-3 py-1.5">
                <span className="w-44 text-xs">{formatDate(l.at, locale)}</span>
                <span>{l.action === "auth.registered" ? u.signup : u.signin}</span>
                <span dir="ltr" className="font-mono text-xs text-muted-foreground">{l.ip ?? "—"}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

/* ---------------------------------------------------------------- possible duplicates */

function DuplicatesTab({ d, onOpen }: { d: UserDetail; onOpen: (id: string) => void }) {
  const { t, locale } = useI18n();
  const u = t.admin.users;
  if (!d.duplicates.length) return <p className="text-sm text-muted-foreground">{u.noDuplicates}</p>;
  return (
    <div>
      <ul className="space-y-2">
        {d.duplicates.map((m) => (
          <li key={m.user_id} className={cn("rounded-lg border p-3", m.strong ? "border-destructive/40 bg-destructive/5" : "border-sun-500/40 bg-sun-500/5")}>
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-medium">{m.full_name || "—"}</p>
              <span className="text-xs text-muted-foreground" dir="ltr">{m.email}</span>
              <Badge tone={APPROVAL_TONE[m.approval_status]}>{u.status[m.approval_status]}</Badge>
              <Badge tone={m.strong ? "red" : "yellow"}>{m.strong ? u.strong : u.weak}</Badge>
              <Button size="sm" variant="ghost" className="ms-auto h-7" onClick={() => onOpen(m.user_id)}>
                {u.open} <ExternalLink className="size-3" aria-hidden />
              </Button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {m.kinds.map((k) => (
                <Badge key={k} tone={STRONG.includes(k) ? "red" : "neutral"} title={m.values[k]}>
                  {u.signals[k]}
                  {k === "ip" || k === "phone" ? <span dir="ltr" className="font-mono">: {m.values[k]}</span> : null}
                </Badge>
              ))}
            </div>
            <p className="mt-1.5 text-[11px] text-muted-foreground">{u.signedUpOn.replace("{date}", formatDate(m.created_at, locale))}</p>
          </li>
        ))}
      </ul>
      {d.duplicates.some((m) => !m.strong) ? <p className="mt-2 text-xs text-muted-foreground">{u.weakHint}</p> : null}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function Item({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{k}</dt>
      <dd className="mt-0.5 break-words">{v}</dd>
    </div>
  );
}
