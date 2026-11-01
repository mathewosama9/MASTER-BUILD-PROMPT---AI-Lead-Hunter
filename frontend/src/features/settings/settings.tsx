"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
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
  Th,
} from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useMe } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { Role } from "@/types/api";

import { BusinessProfileTab } from "./business-profile";

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
  const save = useMutation({
    mutationFn: () => api("/settings", { method: "PUT", body: { scoring_weights: weights, retention_days: retention } }),
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

type LinkCode = { code: string; expires_at: string; bot_username: string | null; deep_link: string | null };

function TelegramTab({ isAdmin }: { isAdmin: boolean }) {
  const { t, locale, label } = useI18n();
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ["tg-accounts"], queryFn: () => api<{ id: string; user_email: string; telegram_user_id: number; username: string | null; status: string; created_at: string }[]>("/telegram/accounts") });
  const [code, setCode] = useState<LinkCode | null>(null);
  const gen = useMutation({
    mutationFn: () => api<LinkCode>("/telegram/link-code", { method: "POST" }),
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
            <div className="space-y-2 rounded-md border border-sun-500/40 bg-sun-500/10 p-4">
              {code.deep_link ? (
                <Button asChild>
                  <a href={code.deep_link} target="_blank" rel="noopener noreferrer"><Send /> {t.settings.openBot}</a>
                </Button>
              ) : null}
              <p className="text-xs text-muted-foreground">{code.deep_link ? t.settings.openBotHint : t.settings.linkInstructions}{code.bot_username ? ` @${code.bot_username}` : ""}</p>
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

export function SettingsPage() {
  const { t, locale } = useI18n();
  const { data: me } = useMe();
  const isAdmin = me?.role === "admin" || me?.role === "owner";
  // Deep links such as /app/settings?tab=telegram (from the overview checklist) open that tab.
  // The app renders only in the browser (after /auth/me), so reading the URL here cannot mismatch hydration.
  const [tab, setTab] = useState(() =>
    typeof window === "undefined" ? "business" : (new URLSearchParams(window.location.search).get("tab") ?? "business"),
  );
  return (
    <div>
      <PageHeader title={t.settings.title} />
      <Tabs value={tab} onValueChange={setTab} dir={locale === "ar" ? "rtl" : "ltr"}>
        <TabsList>
          <TabsTrigger value="business">{t.business.tab}</TabsTrigger>
          <TabsTrigger value="workspace">{t.settings.workspace}</TabsTrigger>
          <TabsTrigger value="users">{t.settings.users}</TabsTrigger>
          <TabsTrigger value="telegram">{t.settings.telegram}</TabsTrigger>
          {isAdmin ? <TabsTrigger value="audit">{t.settings.audit}</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="business"><BusinessProfileTab canEdit={isAdmin} /></TabsContent>
        <TabsContent value="workspace"><WorkspaceSettings canEdit={isAdmin} /></TabsContent>
        <TabsContent value="users"><UsersTab canEdit={isAdmin} /></TabsContent>
        <TabsContent value="telegram"><TelegramTab isAdmin={isAdmin} /></TabsContent>
        {isAdmin ? <TabsContent value="audit"><AuditTab /></TabsContent> : null}
      </Tabs>
    </div>
  );
}
