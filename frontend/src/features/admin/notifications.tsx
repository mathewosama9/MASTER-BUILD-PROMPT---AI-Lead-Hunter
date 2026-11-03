"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, Megaphone, Send, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardContent,
  Checkbox,
  Dialog,
  Field,
  Input,
  Select,
  Switch,
  Table,
  Td,
  Textarea,
  Th,
} from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { formatDate, formatNumber } from "@/lib/utils";
import type { NotifyChannel, Page } from "@/types/api";

const CHANNELS: NotifyChannel[] = ["in_app", "email", "telegram"];
const AUDIENCES = ["all", "trial", "paying", "low_balance", "inactive_30d", "suspended", "admins", "users"] as const;
type AudienceType = (typeof AUDIENCES)[number];

interface KindPolicy {
  key: string;
  category: string;
  mandatory: boolean;
  admin: boolean;
  enabled: boolean;
  channels: Record<NotifyChannel, boolean>;
  user_can_disable: boolean;
}
interface PolicyOut {
  kinds: KindPolicy[];
  email_rate_per_minute: number;
  smtp_configured: boolean;
  telegram_configured: boolean;
  pending: number;
  failed_24h: number;
}
interface Recipient {
  id: string;
  email: string;
  full_name: string;
}
interface BroadcastRow {
  id: string;
  kind: "announcement" | "marketing";
  title_ar: string;
  title_en: string;
  audience: { type: AudienceType; ids: string[] };
  channels: NotifyChannel[];
  status: string;
  recipients: number;
  created_at: string;
  created_by_email: string | null;
  stats: { in_app: number; read: number; email: Record<string, number>; telegram: Record<string, number> };
}

const onError = (e: Error) => toast.error(e.message);

export function NotificationsAdmin() {
  return (
    <div className="space-y-6">
      <Composer />
      <History />
      <PolicyEditor />
    </div>
  );
}

/* ---------------------------------------------------------------- policy */

function PolicyEditor() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-notify-policy"],
    queryFn: () => api<PolicyOut>("/admin/notifications/policy"),
  });
  if (isLoading) return <LoadingState />;
  if (error || !data) return <ErrorState error={error} />;
  // Keyed by the loaded data so the form re-initialises from server state without effects.
  return <PolicyForm key={JSON.stringify(data)} data={data} />;
}

function PolicyForm({ data }: { data: PolicyOut }) {
  const { t, locale } = useI18n();
  const qc = useQueryClient();
  const [kinds, setKinds] = useState(data.kinds);
  const [rate, setRate] = useState(data.email_rate_per_minute);
  const a = t.notify.admin;
  const save = useMutation({
    mutationFn: () =>
      api<PolicyOut>("/admin/notifications/policy", {
        method: "PUT",
        body: {
          policy: Object.fromEntries(kinds.map((k) => [k.key, { enabled: k.enabled, channels: k.channels, user_can_disable: k.user_can_disable }])),
          email_rate_per_minute: rate,
        },
      }),
    onSuccess: (out) => {
      qc.setQueryData(["admin-notify-policy"], out);
      toast.success(t.common.saved);
    },
    onError,
  });
  const testEmail = useMutation({
    mutationFn: () => api<{ message: string }>("/admin/notifications/test-email", { method: "POST" }),
    onSuccess: (r) => toast.success(r.message),
    onError,
  });
  const patch = (key: string, change: Partial<KindPolicy>) => setKinds((ks) => ks.map((k) => (k.key === key ? { ...k, ...change } : k)));
  const status = (ok: boolean) => <Badge tone={ok ? "green" : "red"}>{ok ? a.connected : a.notConnected}</Badge>;

  return (
    <Card>
      <CardContent className="space-y-5 p-6">
        <div>
          <p className="text-sm font-semibold">{a.policyTitle}</p>
          <p className="mt-1 text-xs text-muted-foreground">{a.policyHint}</p>
        </div>
        <div className="grid gap-3 text-sm sm:grid-cols-3">
          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">{a.smtp}</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {status(data.smtp_configured)}
              {data.smtp_configured ? (
                <Button size="sm" variant="ghost" disabled={testEmail.isPending} onClick={() => testEmail.mutate()}>
                  <Mail /> {a.testEmail}
                </Button>
              ) : null}
            </div>
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">{a.telegram}</p>
            <div className="mt-1">{status(data.telegram_configured)}</div>
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">{a.queue}</p>
            <p className="mt-1 text-xs">
              {a.queueText.replace("{pending}", formatNumber(data.pending, locale)).replace("{failed}", formatNumber(data.failed_24h, locale))}
            </p>
          </div>
        </div>
        <Field label={a.emailRate} htmlFor="email-rate" hint={a.emailRateHint}>
          <Input id="email-rate" type="number" min={1} max={1000} className="w-32" value={rate} onChange={(e) => setRate(Number(e.target.value))} />
        </Field>
        <div className="-mx-6">
          <Table>
            <thead className="border-b">
              <tr>
                <Th className="ps-6">{a.kind}</Th>
                <Th className="text-center">{a.enabled}</Th>
                {CHANNELS.map((c) => (
                  <Th key={c} className="text-center">
                    {t.notify.channels[c]}
                  </Th>
                ))}
                <Th className="pe-6 text-center">{a.userCanDisable}</Th>
              </tr>
            </thead>
            <tbody>
              {kinds.map((k) => {
                const name = t.notify.kinds[k.key] ?? k.key;
                return (
                  <tr key={k.key} className="border-b last:border-0">
                    <Td className="ps-6">
                      <span className="text-sm">{name}</span>
                      <span className="ms-2 text-[11px] text-muted-foreground">
                        {k.mandatory ? a.mandatory : k.admin ? a.adminOnly : t.notify.categories[k.category]}
                      </span>
                    </Td>
                    <Td className="text-center">
                      <Switch aria-label={`${name}: ${a.enabled}`} checked={k.enabled} onCheckedChange={(v) => patch(k.key, { enabled: v })} />
                    </Td>
                    {CHANNELS.map((c) => (
                      <Td key={c} className="text-center">
                        <Checkbox
                          aria-label={`${name}: ${t.notify.channels[c]}`}
                          checked={k.channels[c]}
                          onCheckedChange={(v) => patch(k.key, { channels: { ...k.channels, [c]: v } })}
                        />
                      </Td>
                    ))}
                    <Td className="pe-6 text-center">
                      {k.mandatory || k.admin ? (
                        <span className="text-xs text-muted-foreground">—</span>
                      ) : (
                        <Checkbox
                          aria-label={`${name}: ${a.userCanDisable}`}
                          checked={k.user_can_disable}
                          onCheckedChange={(v) => patch(k.key, { user_can_disable: v })}
                        />
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </div>
        <Button onClick={() => save.mutate()} disabled={save.isPending || rate < 1}>
          {t.common.save}
        </Button>
      </CardContent>
    </Card>
  );
}

/* ---------------------------------------------------------------- compose */

const EMPTY = { kind: "announcement" as "announcement" | "marketing", title_ar: "", title_en: "", body_ar: "", body_en: "", link: "" };

function Composer() {
  const { t, locale } = useI18n();
  const qc = useQueryClient();
  const a = t.notify.admin;
  const [form, setForm] = useState(EMPTY);
  const [audience, setAudience] = useState<AudienceType>("all");
  const [picked, setPicked] = useState<Recipient[]>([]);
  const [channels, setChannels] = useState<NotifyChannel[]>(["in_app", "email"]);
  const [q, setQ] = useState("");
  const [confirm, setConfirm] = useState(false);

  const audienceBody = { type: audience, ids: audience === "users" ? picked.map((p) => p.id) : [] };
  const audienceReady = audience !== "users" || picked.length > 0;
  const preview = useQuery({
    queryKey: ["admin-broadcast-preview", audienceBody],
    queryFn: () => api<{ recipients: number }>("/admin/broadcasts/preview", { method: "POST", body: audienceBody }),
    enabled: audienceReady,
  });
  const found = useQuery({
    queryKey: ["admin-recipients", q],
    queryFn: () => api<Recipient[]>("/admin/notifications/recipients", { query: { q } }),
    enabled: audience === "users" && q.trim().length >= 2,
  });
  const body = () => ({ ...form, link: form.link.trim() || null, audience: audienceBody, channels });
  const test = useMutation({
    mutationFn: () => api("/admin/broadcasts/test", { method: "POST", body: body() }),
    onSuccess: () => {
      toast.success(a.testQueued);
      void qc.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError,
  });
  const send = useMutation({
    mutationFn: () => api("/admin/broadcasts", { method: "POST", body: body() }),
    onSuccess: () => {
      toast.success(a.sent);
      setConfirm(false);
      setForm(EMPTY);
      setPicked([]);
      void qc.invalidateQueries({ queryKey: ["admin-broadcasts"] });
      void qc.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError,
  });
  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));
  const count = preview.data?.recipients ?? 0;
  const valid = (form.title_ar.trim() || form.title_en.trim()) && channels.length > 0 && audienceReady;

  return (
    <Card>
      <CardContent className="space-y-5 p-6">
        <div>
          <p className="flex items-center gap-2 text-sm font-semibold">
            <Megaphone className="size-4" aria-hidden /> {a.composeTitle}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{a.composeHint}</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={a.type} htmlFor="bc-kind">
            <Select id="bc-kind" value={form.kind} onChange={set("kind")}>
              <option value="announcement">{a.typeAnnouncement}</option>
              <option value="marketing">{a.typeMarketing}</option>
            </Select>
          </Field>
          <Field label={a.audience} htmlFor="bc-audience">
            <Select id="bc-audience" value={audience} onChange={(e) => setAudience(e.target.value as AudienceType)}>
              {AUDIENCES.map((x) => (
                <option key={x} value={x}>
                  {a.audiences[x]}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {audience === "users" ? (
          <div className="space-y-2">
            <Input aria-label={a.searchUsers} placeholder={a.searchUsers} value={q} onChange={(e) => setQ(e.target.value)} />
            {found.data?.length ? (
              <div className="max-h-40 overflow-y-auto rounded-lg border">
                {found.data
                  .filter((u) => !picked.some((p) => p.id === u.id))
                  .map((u) => (
                    <button
                      key={u.id}
                      type="button"
                      onClick={() => setPicked((ps) => [...ps, u])}
                      className="block w-full px-3 py-2 text-start text-sm hover:bg-muted"
                    >
                      {u.email}
                      {u.full_name ? <span className="ms-2 text-xs text-muted-foreground">{u.full_name}</span> : null}
                    </button>
                  ))}
              </div>
            ) : null}
            {picked.length ? (
              <div className="flex flex-wrap gap-1.5">
                {picked.map((u) => (
                  <Badge key={u.id} tone="blue">
                    {u.email}
                    <button type="button" aria-label={`${t.common.remove} ${u.email}`} onClick={() => setPicked((ps) => ps.filter((p) => p.id !== u.id))}>
                      <X className="size-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={a.titleAr} htmlFor="bc-title-ar">
            <Input id="bc-title-ar" dir="rtl" maxLength={300} value={form.title_ar} onChange={set("title_ar")} />
          </Field>
          <Field label={a.titleEn} htmlFor="bc-title-en">
            <Input id="bc-title-en" dir="ltr" maxLength={300} value={form.title_en} onChange={set("title_en")} />
          </Field>
          <Field label={a.bodyAr} htmlFor="bc-body-ar">
            <Textarea id="bc-body-ar" dir="rtl" rows={4} maxLength={4000} value={form.body_ar} onChange={set("body_ar")} />
          </Field>
          <Field label={a.bodyEn} htmlFor="bc-body-en">
            <Textarea id="bc-body-en" dir="ltr" rows={4} maxLength={4000} value={form.body_en} onChange={set("body_en")} />
          </Field>
        </div>
        <p className="-mt-2 text-xs text-muted-foreground">{a.bodyHint}</p>
        <Field label={a.link} htmlFor="bc-link" hint={a.linkHint}>
          <Input id="bc-link" dir="ltr" maxLength={500} placeholder="/app/billing" value={form.link} onChange={set("link")} />
        </Field>
        <fieldset>
          <legend className="mb-2 text-sm font-medium">{a.channels}</legend>
          <div className="flex flex-wrap gap-4">
            {CHANNELS.map((c) => (
              <label key={c} className="flex items-center gap-2 text-sm">
                <Checkbox
                  aria-label={t.notify.channels[c]}
                  checked={channels.includes(c)}
                  onCheckedChange={(v) => setChannels((cs) => (v ? [...cs, c] : cs.filter((x) => x !== c)))}
                />
                {t.notify.channels[c]}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex flex-wrap items-center gap-3 border-t pt-4">
          <p className="me-auto text-sm text-muted-foreground">{audienceReady ? a.recipients.replace("{n}", formatNumber(count, locale)) : null}</p>
          <Button variant="outline" disabled={!valid || test.isPending} onClick={() => test.mutate()}>
            {a.sendTest}
          </Button>
          <Button variant="ink" disabled={!valid || !count} onClick={() => setConfirm(true)}>
            <Send /> {a.send}
          </Button>
        </div>
      </CardContent>
      <Dialog
        open={confirm}
        onOpenChange={setConfirm}
        title={a.confirmTitle}
        description={a.confirmText.replace("{n}", formatNumber(count, locale))}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(false)}>
              {t.common.cancel}
            </Button>
            <Button variant="ink" disabled={send.isPending} onClick={() => send.mutate()}>
              <Send /> {a.send}
            </Button>
          </>
        }
      >
        <div className="rounded-lg border p-3 text-sm">
          <p className="font-semibold">{(locale === "ar" ? form.title_ar : form.title_en) || form.title_ar || form.title_en}</p>
          <p className="mt-1 whitespace-pre-line text-muted-foreground">{(locale === "ar" ? form.body_ar : form.body_en) || form.body_ar || form.body_en}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            {a.audiences[audience]} · {channels.map((c) => t.notify.channels[c]).join("، ")}
          </p>
        </div>
      </Dialog>
    </Card>
  );
}

/* ---------------------------------------------------------------- history */

function sum(x: Record<string, number>) {
  return Object.values(x).reduce((s, n) => s + n, 0);
}

function History() {
  const { t, locale } = useI18n();
  const a = t.notify.admin;
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-broadcasts"],
    queryFn: () => api<Page<BroadcastRow>>("/admin/broadcasts"),
    refetchInterval: (q) => (q.state.data?.items.some((b) => b.status === "sending" || sum(b.stats.email) > (b.stats.email.sent ?? 0) + (b.stats.email.failed ?? 0) + (b.stats.email.skipped ?? 0)) ? 10_000 : false),
  });
  if (isLoading) return <LoadingState rows={2} />;
  if (error) return <ErrorState error={error} />;
  return (
    <Card>
      <CardContent className="p-6">
        <p className="mb-3 text-sm font-semibold">{a.historyTitle}</p>
        {!data?.items.length ? (
          <p className="text-sm text-muted-foreground">{a.historyEmpty}</p>
        ) : (
          <div className="-mx-6">
            <Table>
              <tbody>
                {data.items.map((b) => {
                  const failed = (b.stats.email.failed ?? 0) + (b.stats.telegram.failed ?? 0);
                  return (
                    <tr key={b.id} className="border-b align-top last:border-0">
                      <Td className="ps-6">
                        <p className="text-sm font-medium">{(locale === "ar" ? b.title_ar : b.title_en) || b.title_ar || b.title_en}</p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {b.kind === "marketing" ? a.typeMarketing : a.typeAnnouncement} · {a.audiences[b.audience.type]}
                          {b.audience.type === "users" ? ` (${b.audience.ids.length})` : ""} · {b.channels.map((c) => t.notify.channels[c]).join("، ")}
                        </p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {a.stats
                            .replace("{inApp}", formatNumber(b.stats.in_app, locale))
                            .replace("{read}", formatNumber(b.stats.read, locale))
                            .replace("{email}", formatNumber(b.stats.email.sent ?? 0, locale))
                            .replace("{telegram}", formatNumber(b.stats.telegram.sent ?? 0, locale))}
                          {failed ? <span className="ms-2 text-destructive">{a.failedN.replace("{n}", formatNumber(failed, locale))}</span> : null}
                        </p>
                      </Td>
                      <Td className="whitespace-nowrap text-xs text-muted-foreground">
                        {formatDate(b.created_at, locale)}
                        {b.created_by_email ? <p>{b.created_by_email}</p> : null}
                      </Td>
                      <Td className="pe-6 text-end">
                        <Badge tone={b.status === "sent" ? "green" : "yellow"}>{a.status[b.status] ?? b.status}</Badge>
                        <p className="mt-1 text-xs tabular-nums text-muted-foreground">{formatNumber(b.recipients, locale)}</p>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
