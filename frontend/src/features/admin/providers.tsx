"use client";

// Platform-wide API keys and linked social accounts. Managed by platform admins only (the API refuses everyone
// else); customers never see keys, costs or provider names.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, KeyRound, PlugZap, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ProviderStatusBadge } from "@/components/badges";
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
  Switch,
  Textarea,
} from "@/components/ui/primitives";
import { ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { useProviders } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { formatMoney } from "@/lib/utils";
import type { Provider } from "@/types/api";

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
  const remove = useMutation({
    mutationFn: () =>
      api(`/providers/${p.key}`, { method: "PUT", body: { credentials: Object.fromEntries(fields.map((f) => [f, ""])) } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["providers"] }); toast.success(t.settings.keyRemoved); },
    onError: (e: Error) => toast.error(e.message),
  });
  const fields = p.requires.filter((r) => r !== "manual_urls");
  // Brave, Gemini and Perplexity take several API keys (one per line), used in turn by the backend.
  const multiKey = ["brave", "gemini", "perplexity"].includes(p.key);
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
        {p.credential_source === "env" ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><KeyRound className="size-3.5" /> {t.settings.envReplaceHint}</p>
        ) : null}
        {fields.map((f) => (
            <Field key={f} label={label(f)} htmlFor={`${p.key}-${f}`} hint={[multiKey ? t.settings.multiKeyHint : null, p.credentials_masked[f] ? `${t.common.current}: ${p.credentials_masked[f]}` : null].filter(Boolean).join(" ") || undefined}>
              {f === "credentials_json" || multiKey ? (
                <Textarea id={`${p.key}-${f}`} dir={multiKey ? "ltr" : undefined} autoComplete="off" disabled={!canEdit} rows={3} value={creds[f] ?? ""} onChange={(e) => setCreds({ ...creds, [f]: e.target.value })} />
              ) : (
                <Input id={`${p.key}-${f}`} type="password" autoComplete="off" disabled={!canEdit} value={creds[f] ?? ""} onChange={(e) => setCreds({ ...creds, [f]: e.target.value })} />
              )}
            </Field>
        ))}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
          <div className="flex items-center gap-2 text-xs">
            <Switch id={`${p.key}-enabled`} checked={p.enabled} disabled={!canEdit} onCheckedChange={(v) => save.mutate({ enabled: v })} />
            <label htmlFor={`${p.key}-enabled`}>{t.settings.enabled}</label>
            <span className="text-muted-foreground">· {t.settings.usage}: {p.usage_month.requests} {t.settings.requests} · {formatMoney(p.usage_month.cost_usd)}</span>
          </div>
          <div className="flex gap-1.5">
            {p.docs_url ? <Button asChild size="sm" variant="ghost"><a href={p.docs_url} target="_blank" rel="noopener noreferrer"><ExternalLink /> {t.common.docs}</a></Button> : null}
            {canEdit && fields.length ? (
              <Button size="sm" variant="outline" disabled={!Object.values(creds).some(Boolean) || save.isPending} onClick={() => save.mutate({ credentials: creds })}>{t.settings.save}</Button>
            ) : null}
            {/* A saved key can be deleted to put in another one (or to fall back to the server's env key). */}
            {canEdit && fields.length && (p.credential_source === "platform" || p.credential_source === "workspace") ? (
              <Button
                size="sm"
                variant="ghost"
                className="text-destructive"
                disabled={remove.isPending}
                onClick={() => confirm((p.has_env_key ? t.settings.removeKeyEnvConfirm : t.settings.removeKeyConfirm).replace("{name}", p.name)) && remove.mutate()}
              >
                {remove.isPending ? <Spinner /> : <Trash2 />} {t.settings.removeKey}
              </Button>
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

export function ProvidersAdmin() {
  const { t } = useI18n();
  const providers = useProviders();
  if (providers.isLoading) return <LoadingState />;
  if (providers.error) return <ErrorState error={providers.error} />;
  return (
    <>
      <p className="mb-4 text-xs text-muted-foreground">{t.settings.secretsNote}</p>
      <div className="grid gap-4 lg:grid-cols-2">
        {providers.data!.map((p) => (
          <ProviderCard key={p.key} p={p} canEdit />
        ))}
      </div>
      <LinkedAccounts canEdit />
    </>
  );
}
