"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, KeyRound, PlugZap, Send } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ProviderStatusBadge } from "@/components/badges";
import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
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
import { useMe, useProviders } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/utils";
import type { Provider, Role } from "@/types/api";

function ProviderCard({ p, canEdit }: { p: Provider; canEdit: boolean }) {
  const { t, label } = useI18n();
  const qc = useQueryClient();
  const [creds, setCreds] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api(`/providers/${p.key}`, { method: "PUT", body }),
    onSuccess: () => { setCreds({}); qc.invalidateQueries({ queryKey: ["providers"] }); toast.success(t.common.saved); },
    onError: (e: Error) => toast.error(e.message),
  });
  const test = useMutation({
    mutationFn: () => api<{ status: string; detail: string | null }>(`/providers/${p.key}/test`, { method: "POST" }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["providers"] });
      (r.status === "connected" ? toast.success : toast.warning)(`${p.name}: ${t.providerStatus[r.status as keyof typeof t.providerStatus] ?? r.status}${r.detail ? ` — ${r.detail}` : ""}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const fields = p.requires.filter((r) => r !== "manual_urls");
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2">{p.name}<Badge tone="neutral">{label(p.kind)}</Badge></CardTitle>
            <CardDescription className="mt-1">{(t.providerDesc as Record<string, string>)[p.key] ?? p.description}</CardDescription>
          </div>
          <ProviderStatusBadge status={p.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {p.status_detail ? <p className="text-xs text-muted-foreground">{p.status_detail}</p> : null}
        {p.last_error ? <p className="text-xs text-destructive">{p.last_error}</p> : null}
        {fields.map((f) =>
          p.credential_source === "env" ? (
            <p key={f} className="flex items-center gap-1.5 text-xs text-muted-foreground"><KeyRound className="size-3.5" /> {label(f)}: {p.credentials_masked[f] ?? "—"} ({t.settings.credentialFromEnv})</p>
          ) : (
            <Field key={f} label={label(f)} htmlFor={`${p.key}-${f}`} hint={p.credentials_masked[f] ? `${t.common.current}: ${p.credentials_masked[f]}` : undefined}>
              {f === "credentials_json" ? (
                <Textarea id={`${p.key}-${f}`} disabled={!canEdit} rows={3} value={creds[f] ?? ""} onChange={(e) => setCreds({ ...creds, [f]: e.target.value })} />
              ) : (
                <Input id={`${p.key}-${f}`} type="password" autoComplete="off" disabled={!canEdit} value={creds[f] ?? ""} onChange={(e) => setCreds({ ...creds, [f]: e.target.value })} />
              )}
            </Field>
          ),
        )}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
          <div className="flex items-center gap-2 text-xs">
            <Switch id={`${p.key}-enabled`} checked={p.enabled} disabled={!canEdit} onCheckedChange={(v) => save.mutate({ enabled: v })} />
            <label htmlFor={`${p.key}-enabled`}>{t.settings.enabled}</label>
            <span className="text-muted-foreground">· {t.settings.usage}: {p.usage_month.requests} {t.settings.requests} · {formatMoney(p.usage_month.cost_usd)}</span>
          </div>
          <div className="flex gap-1.5">
            {p.docs_url ? <Button asChild size="sm" variant="ghost"><a href={p.docs_url} target="_blank" rel="noopener noreferrer"><ExternalLink /> {t.common.docs}</a></Button> : null}
            {canEdit && fields.length && p.credential_source !== "env" ? (
              <Button size="sm" variant="outline" disabled={!Object.values(creds).some(Boolean) || save.isPending} onClick={() => save.mutate({ credentials: creds })}>{t.settings.save}</Button>
            ) : null}
            {canEdit ? (
              <Button size="sm" onClick={() => test.mutate()} disabled={test.isPending}>{test.isPending ? <Spinner /> : <PlugZap />} {t.settings.testConnection}</Button>
            ) : null}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function WorkspaceSettings({ canEdit }: { canEdit: boolean }) {
  const { data, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: () => api<Record<string, unknown>>("/settings") });
  if (isLoading) return <LoadingState />;
  if (error || !data) return <ErrorState error={error} />;
  // Keyed by the loaded data so the form re-initialises from server state without effects.
  return <WorkspaceSettingsForm key={JSON.stringify(data)} data={data} canEdit={canEdit} />;
}

function WorkspaceSettingsForm({ data, canEdit }: { data: Record<string, unknown>; canEdit: boolean }) {
  const { t, label } = useI18n();
  const qc = useQueryClient();
  const [weights, setWeights] = useState<Record<string, number>>(data.scoring_weights as Record<string, number>);
  const [retention, setRetention] = useState(Number(data.retention_days));
  const [named, setNamed] = useState(Boolean(data.allow_named_contacts));
  const save = useMutation({
    mutationFn: () => api("/settings", { method: "PUT", body: { scoring_weights: weights, retention_days: retention, allow_named_contacts: named } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); toast.success(t.common.saved); },
    onError: (e: Error) => toast.error(e.message),
  });
  const total = Object.values(weights).reduce((a, b) => a + Number(b || 0), 0);
  return (
    <Card>
      <CardContent className="space-y-5 p-6">
        <div>
          <p className="mb-1 text-sm font-medium">{t.settings.weights}</p>
          <p className="mb-3 text-xs text-muted-foreground">{t.settings.weightsHint.replace("{n}", String(Math.round(total * 100)))}</p>
          <div className="grid gap-3 sm:grid-cols-3">
            {Object.entries(weights).map(([k, v]) => (
              <Field key={k} label={label(k)} htmlFor={`w-${k}`}>
                <Input id={`w-${k}`} type="number" step="0.05" min={0} max={1} disabled={!canEdit} value={v}
                       onChange={(e) => setWeights({ ...weights, [k]: Number(e.target.value) })} />
              </Field>
            ))}
          </div>
        </div>
        <Field label={t.settings.retention} htmlFor="retention" hint={t.settings.retentionHint}>
          <Input id="retention" type="number" min={30} max={3650} className="w-40" disabled={!canEdit} value={retention} onChange={(e) => setRetention(Number(e.target.value))} />
        </Field>
        <div className="flex items-center justify-between gap-4 rounded-md border p-3">
          <label htmlFor="named" className="text-sm">{t.settings.namedContacts}<p className="text-xs text-muted-foreground">{t.settings.namedHint}</p></label>
          <Switch id="named" checked={named} disabled={!canEdit} onCheckedChange={setNamed} />
        </div>
        {canEdit ? <Button onClick={() => save.mutate()} disabled={save.isPending}>{t.common.save}</Button> : null}
      </CardContent>
    </Card>
  );
}

function UsersTab({ canEdit }: { canEdit: boolean }) {
  const { t, label } = useI18n();
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["users"], queryFn: () => api<{ user: { id: string; email: string; full_name: string; is_active: boolean }; role: Role }[]>("/users") });
  const [form, setForm] = useState({ email: "", password: "", full_name: "", role: "analyst" });
  const create = useMutation({
    mutationFn: () => api("/users", { method: "POST", body: form }),
    onSuccess: () => { setForm({ email: "", password: "", full_name: "", role: "analyst" }); qc.invalidateQueries({ queryKey: ["users"] }); toast.success(t.settings.userAdded); },
    onError: (e: Error) => toast.error(e.message),
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api(`/users/${id}`, { method: "PATCH", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
    onError: (e: Error) => toast.error(e.message),
  });
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  return (
    <div className="space-y-4">
      <Card>
        <Table>
          <thead className="border-b"><tr><Th>{t.settings.email}</Th><Th>{t.settings.name}</Th><Th>{t.settings.role}</Th><Th>{t.settings.active}</Th></tr></thead>
          <tbody>
            {data?.map((m) => (
              <tr key={m.user.id} className="border-b last:border-0">
                <Td>{m.user.email}</Td>
                <Td>{m.user.full_name}</Td>
                <Td>
                  <Select aria-label={t.settings.role} className="h-8 w-32" disabled={!canEdit} value={m.role} onChange={(e) => update.mutate({ id: m.user.id, body: { role: e.target.value } })}>
                    {["owner", "admin", "analyst", "viewer"].map((r) => <option key={r} value={r}>{label(r)}</option>)}
                  </Select>
                </Td>
                <Td><Switch aria-label={t.settings.active} checked={m.user.is_active} disabled={!canEdit} onCheckedChange={(v) => update.mutate({ id: m.user.id, body: { is_active: v } })} /></Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      {canEdit ? (
        <Card>
          <CardHeader><CardTitle>{t.settings.addUser}</CardTitle></CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-4">
            <Input aria-label={t.settings.email} placeholder={t.settings.email} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <Input aria-label={t.settings.name} placeholder={t.settings.name} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
            <Input aria-label={t.auth.password} type="password" placeholder={t.settings.passwordPlaceholder} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <div className="flex gap-2">
              <Select aria-label={t.settings.role} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {["admin", "analyst", "viewer"].map((r) => <option key={r} value={r}>{label(r)}</option>)}
              </Select>
              <Button onClick={() => create.mutate()} disabled={create.isPending}>{t.common.save}</Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function TelegramTab({ isAdmin }: { isAdmin: boolean }) {
  const { t, locale, label } = useI18n();
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ["tg-accounts"], queryFn: () => api<{ id: string; user_email: string; telegram_user_id: number; username: string | null; status: string; created_at: string }[]>("/telegram/accounts") });
  const [code, setCode] = useState<{ code: string; expires_at: string; bot_username: string | null } | null>(null);
  const gen = useMutation({
    mutationFn: () => api<{ code: string; expires_at: string; bot_username: string | null }>("/telegram/link-code", { method: "POST" }),
    onSuccess: setCode,
    onError: (e: Error) => toast.error(e.message),
  });
  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) => api(`/telegram/accounts/${id}/${action}`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tg-accounts"] }),
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-3 p-6">
          <p className="text-sm">{t.settings.telegramIntro}</p>
          <Button onClick={() => gen.mutate()} disabled={gen.isPending}><Send /> {t.settings.linkCode}</Button>
          {code ? (
            <div className="rounded-md border border-sun-500/40 bg-sun-500/10 p-4">
              <p className="text-xs text-muted-foreground">{t.settings.linkInstructions}{code.bot_username ? ` @${code.bot_username}` : ""}</p>
              <p className="mt-2 font-mono text-lg font-semibold tracking-widest" dir="ltr">/link {code.code}</p>
              <p className="mt-1 text-xs text-muted-foreground">{t.common.expires}: {formatDate(code.expires_at, locale)}</p>
            </div>
          ) : null}
        </CardContent>
      </Card>
      <Card>
        <Table>
          <thead className="border-b"><tr><Th>{t.settings.user}</Th><Th>{t.settings.telegram}</Th><Th>{t.settings.status}</Th><Th>{t.settings.linked}</Th><Th /></tr></thead>
          <tbody>
            {accounts.data?.map((a) => (
              <tr key={a.id} className="border-b last:border-0">
                <Td>{a.user_email}</Td>
                <Td>{a.username ? `@${a.username}` : a.telegram_user_id}</Td>
                <Td><Badge tone={a.status === "approved" ? "green" : a.status === "pending" ? "yellow" : "neutral"}>{label(a.status)}</Badge></Td>
                <Td className="text-xs text-muted-foreground">{formatDate(a.created_at, locale)}</Td>
                <Td className="text-end">
                  {isAdmin && a.status === "pending" ? <Button size="sm" onClick={() => act.mutate({ id: a.id, action: "approve" })}>{t.settings.approve}</Button> : null}
                  {a.status !== "revoked" ? <Button size="sm" variant="ghost" onClick={() => act.mutate({ id: a.id, action: "revoke" })}>{t.settings.revoke}</Button> : null}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}

function AuditTab() {
  const { t, locale, label } = useI18n();
  const { data, isLoading, error } = useQuery({ queryKey: ["audit"], queryFn: () => api<{ id: string; action: string; entity_type: string | null; entity_id: string | null; via: string; ip: string | null; created_at: string }[]>("/settings/audit-logs") });
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  return (
    <Card>
      <Table>
        <thead className="border-b"><tr><Th>{t.settings.time}</Th><Th>{t.settings.action}</Th><Th>{t.settings.entity}</Th><Th>{t.settings.via}</Th><Th>{t.settings.ip}</Th></tr></thead>
        <tbody>
          {data?.map((a) => (
            <tr key={a.id} className="border-b text-xs last:border-0">
              <Td className="whitespace-nowrap">{formatDate(a.created_at, locale)}</Td>
              <Td className="font-mono">{a.action}</Td>
              <Td>{a.entity_type ? `${a.entity_type}:${a.entity_id?.slice(0, 8)}` : "—"}</Td>
              <Td>{label(a.via)}</Td>
              <Td>{a.ip ?? "—"}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

interface LinkedSession {
  platform: string;
  status: "connected" | "expired" | "not_connected";
  connected_at: string | null;
  daily_limit: number;
  used_today: number | null;
  login_url: string;
}

/** Social accounts linked by the user's own manual login (scripts/connect_session.py). Cookies are write-only. */
function LinkedAccounts({ canEdit }: { canEdit: boolean }) {
  const { t, label } = useI18n();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["sessions"], queryFn: () => api<LinkedSession[]>("/providers/sessions") });
  const disconnect = useMutation({
    mutationFn: (platform: string) => api(`/providers/sessions/${platform}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
  const [login, setLogin] = useState<{ platform: string; viewer_url: string } | null>(null);
  const start = useMutation({
    mutationFn: (platform: string) =>
      api<{ platform: string; viewer_url: string }>(`/providers/sessions/${platform}/login/start`, { method: "POST" }),
    onSuccess: setLogin,
    onError: (e: Error) => toast.error(e.message),
  });
  const finish = useMutation({
    mutationFn: (platform: string) => api<LinkedSession>(`/providers/sessions/${platform}/login/finish`, { method: "POST" }),
    onSuccess: (s) => {
      setLogin(null);
      toast.success(`${label(s.platform)}: ${t.settings.sessionStatus[s.status]}`);
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
    // e.g. "Not logged in yet": keep the window open so the user can finish and retry.
    onError: (e: Error) => toast.error(e.message),
  });
  const cancel = (platform: string) => {
    setLogin(null);
    void api(`/providers/sessions/${platform}/login/cancel`, { method: "POST" }).catch(() => undefined);
  };
  if (q.isLoading) return <LoadingState rows={2} />;
  if (q.error) return <ErrorState error={q.error} />;
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle className="text-base">{t.settings.linkedAccounts}</CardTitle>
        <CardDescription>{t.settings.linkedAccountsHint}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <ul className="divide-y">
          {q.data!.map((s) => (
            <li key={s.platform} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
              <span className="font-medium">{label(s.platform)}</span>
              <span className="flex items-center gap-2">
                <Badge tone={s.status === "connected" ? "green" : s.status === "expired" ? "red" : "neutral"}>
                  {t.settings.sessionStatus[s.status]}
                </Badge>
                {s.status !== "not_connected" ? (
                  <span className="text-xs text-muted-foreground">
                    {s.used_today ?? "—"}/{s.daily_limit} {t.settings.pagesToday}
                  </span>
                ) : null}
                {canEdit ? (
                  <Button size="sm" onClick={() => start.mutate(s.platform)} disabled={start.isPending}>
                    {start.isPending && start.variables === s.platform ? <Spinner /> : <PlugZap />}
                    {s.status === "connected" ? t.settings.reconnect : t.settings.connect}
                  </Button>
                ) : null}
                {canEdit && s.status !== "not_connected" ? (
                  <Button size="sm" variant="outline" onClick={() => disconnect.mutate(s.platform)} disabled={disconnect.isPending}>
                    {t.settings.disconnect}
                  </Button>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
      {login ? (
        <Dialog
          wide
          open
          onOpenChange={(open) => !open && cancel(login.platform)}
          title={`${t.settings.connect} ${label(login.platform)}`}
          description={t.settings.loginWindowHint}
          footer={
            <>
              <Button variant="outline" onClick={() => cancel(login.platform)}>{t.common.cancel}</Button>
              <Button onClick={() => finish.mutate(login.platform)} disabled={finish.isPending}>
                {finish.isPending ? <Spinner /> : null} {t.settings.loggedInSave}
              </Button>
            </>
          }
        >
          <iframe
            title={`${label(login.platform)} ${t.settings.loginFrame}`}
            src={login.viewer_url}
            className="h-[62vh] w-full rounded-md border bg-black"
            dir="ltr"
          />
        </Dialog>
      ) : null}
    </Card>
  );
}

export function SettingsPage() {
  const { t, locale } = useI18n();
  const { data: me } = useMe();
  const providers = useProviders();
  const isAdmin = me?.role === "admin" || me?.role === "owner";
  return (
    <div>
      <PageHeader title={t.settings.title} />
      <Tabs defaultValue="integrations" dir={locale === "ar" ? "rtl" : "ltr"}>
        <TabsList>
          <TabsTrigger value="integrations">{t.settings.integrations}</TabsTrigger>
          <TabsTrigger value="workspace">{t.settings.workspace}</TabsTrigger>
          <TabsTrigger value="users">{t.settings.users}</TabsTrigger>
          <TabsTrigger value="telegram">{t.settings.telegram}</TabsTrigger>
          {isAdmin ? <TabsTrigger value="audit">{t.settings.audit}</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="integrations">
          {providers.isLoading ? <LoadingState /> : providers.error ? <ErrorState error={providers.error} /> : (
            <>
              <p className="mb-4 text-xs text-muted-foreground">{t.settings.secretsNote}</p>
              <div className="grid gap-4 lg:grid-cols-2">
                {providers.data!.map((p) => <ProviderCard key={p.key} p={p} canEdit={isAdmin} />)}
              </div>
              <LinkedAccounts canEdit={isAdmin} />
            </>
          )}
        </TabsContent>
        <TabsContent value="workspace"><WorkspaceSettings canEdit={isAdmin} /></TabsContent>
        <TabsContent value="users"><UsersTab canEdit={isAdmin} /></TabsContent>
        <TabsContent value="telegram"><TelegramTab isAdmin={isAdmin} /></TabsContent>
        {isAdmin ? <TabsContent value="audit"><AuditTab /></TabsContent> : null}
      </Tabs>
    </div>
  );
}
