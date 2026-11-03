"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeftRight, Ban, Download, Eye, RotateCcw, Search, Send } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, Input, Select, Table, Td, Th } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api, API_BASE, setViewing, stopViewing } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";
import type { Page } from "@/types/api";

const onError = (e: Error) => toast.error(e.message);

/** Download link for an admin CSV export with the filters currently on screen. */
export function CsvButton({ path, query }: { path: string; query?: Record<string, string | number | boolean | undefined> }) {
  const { t } = useI18n();
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== "") params.set(k, String(v));
  const qs = params.toString();
  return (
    <Button size="sm" variant="outline" asChild>
      <a href={`${API_BASE}${path}${qs ? `?${qs}` : ""}`} download>
        <Download /> {t.admin.ops.exportCsv}
      </a>
    </Button>
  );
}

/** Opens the customer's dashboard read-only; the admin's own session comes back from the strip on top. */
export function ViewAsButton({ userId }: { userId: string }) {
  const { t } = useI18n();
  const start = useMutation({
    mutationFn: () => api(`/admin/users/${userId}/impersonate`, { method: "POST" }),
    onSuccess: () => {
      setViewing(true);
      // A full load: nothing cached as the admin can show up in the customer's view.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign(`${window.location.origin}/app`);
    },
    onError,
  });
  return (
    <Button size="sm" variant="outline" title={t.admin.ops.viewAsHint} disabled={start.isPending} onClick={() => start.mutate()}>
      {start.isPending ? <Spinner /> : <Eye />} {t.admin.ops.viewAs}
    </Button>
  );
}

/** Pinned under the top bar while an admin views a customer's account: says it is read-only, and leads back. */
export function ImpersonationStrip({ email }: { email: string }) {
  const { t } = useI18n();
  const stop = useMutation({
    mutationFn: stopViewing,
    onSuccess: (r) => {
      // A full load: drops everything cached as the customer, and the admin page reads ?tab=&user= on its first render.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign(`${window.location.origin}${r.signed_out ? "/login" : `/app/admin?tab=users${r.user_id ? `&user=${r.user_id}` : ""}`}`);
    },
    onError,
  });
  return (
    <div className="sticky top-14 z-20 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-rose-500/40 bg-rose-600 px-4 py-2 text-xs font-medium text-white md:top-16 md:px-6">
      <Eye className="size-4" aria-hidden />
      <span className="min-w-0 flex-1">{t.admin.ops.viewing.replace("{email}", email)}</span>
      <Button size="sm" variant="secondary" className="h-7" disabled={stop.isPending} onClick={() => stop.mutate()}>
        {stop.isPending ? <Spinner /> : <ArrowLeftRight />} {t.admin.ops.backToMine}
      </Button>
    </div>
  );
}

function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  const { t } = useI18n();
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-end gap-2 text-xs">
      <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>{t.common.back}</Button>
      <span className="tabular-nums">{page} / {pages}</span>
      <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>{t.billing.next}</Button>
    </div>
  );
}

/* ---------------------------------------------------------------- activity log */

interface AuditRow {
  id: string;
  created_at: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  data: Record<string, unknown>;
  ip: string | null;
  via: string;
  user_email: string | null;
  user_name: string | null;
  workspace_name: string | null;
}

export function ActivityAdmin() {
  const { t, locale } = useI18n();
  const a = t.admin.ops.activity;
  const [action, setAction] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const actions = useQuery({ queryKey: ["admin-audit-actions"], queryFn: () => api<string[]>("/admin/audit-logs/actions"), staleTime: 300_000 });
  const q = useQuery({
    queryKey: ["admin-audit", action, search, page],
    queryFn: () => api<Page<AuditRow>>("/admin/audit-logs", { query: { action: action || undefined, q: search || undefined, page, page_size: 50 } }),
  });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Select
            aria-label={a.action}
            className="h-9 w-auto max-w-64"
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setPage(1);
            }}
          >
            <option value="">{a.allActions}</option>
            {actions.data?.map((x) => (
              <option key={x} value={x}>{x}</option>
            ))}
          </Select>
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              aria-label={a.search}
              placeholder={a.search}
              className="ps-9"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>
        </div>
        {q.isLoading ? (
          <LoadingState rows={6} />
        ) : q.error ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : !q.data?.items.length ? (
          <EmptyState title={a.empty} />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <thead>
                <tr>
                  <Th>{a.time}</Th>
                  <Th>{a.action}</Th>
                  <Th>{a.actor}</Th>
                  <Th>{a.workspace}</Th>
                  <Th>{a.details}</Th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((r) => {
                  const details = Object.entries(r.data ?? {})
                    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
                    .join(" · ");
                  return (
                    <tr key={r.id}>
                      <Td className="whitespace-nowrap text-xs">{formatDate(r.created_at, locale)}</Td>
                      <Td>
                        <code className="rounded bg-muted px-1.5 py-0.5 text-xs" dir="ltr">{r.action}</code>
                        {r.via !== "web" ? <Badge tone="neutral" className="ms-1.5">{r.via}</Badge> : null}
                      </Td>
                      <Td>
                        {r.user_email ? (
                          <>
                            <p className="text-sm">{r.user_name || "—"}</p>
                            <p className="text-xs text-muted-foreground" dir="ltr">{r.user_email}</p>
                          </>
                        ) : (
                          <span className="text-xs text-muted-foreground">{a.system}</span>
                        )}
                      </Td>
                      <Td className="text-sm">{r.workspace_name ?? "—"}</Td>
                      <Td className="max-w-80 text-xs text-muted-foreground">
                        <p className="truncate" title={details} dir="ltr">{details || "—"}</p>
                        {r.ip ? <p className="font-mono text-[11px]" dir="ltr">{r.ip}</p> : null}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </div>
        )}
        <Pager page={page} pages={pages} onPage={setPage} />
      </CardContent>
    </Card>
  );
}

/* ---------------------------------------------------------------- campaign health */

type HealthKind = "stuck" | "failed" | "running";
interface HealthRow {
  id: string;
  name: string;
  status: string;
  stage: string;
  origin: string;
  workspace_name: string;
  owner_email: string | null;
  run_number: number | null;
  started_at: string | null;
  last_activity_at: string | null;
  last_error: string | null;
  cost_usd: number;
  stuck: boolean;
}
interface HealthSummary {
  stuck: number;
  running: number;
  failed_7d: number;
}

const ACTIVE = ["queued", "discovering", "enriching", "analyzing"];

export function JobsAdmin() {
  const { t, locale, label } = useI18n();
  const j = t.admin.ops.jobs;
  const qc = useQueryClient();
  const [kind, setKind] = useState<HealthKind>("stuck");
  const [page, setPage] = useState(1);
  const summary = useQuery({ queryKey: ["admin-health-summary"], queryFn: () => api<HealthSummary>("/admin/campaigns/health/summary"), refetchInterval: 60_000 });
  const q = useQuery({
    queryKey: ["admin-health", kind, page],
    queryFn: () => api<Page<HealthRow>>("/admin/campaigns/health", { query: { kind, page, page_size: 25 } }),
    refetchInterval: 60_000,
  });
  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "requeue" | "retry" | "cancel" }) => api(`/admin/campaigns/${id}/${action}`, { method: "POST" }),
    onSuccess: (_, v) => {
      toast.success(j.done[v.action]);
      qc.invalidateQueries({ queryKey: ["admin-health"] });
      qc.invalidateQueries({ queryKey: ["admin-health-summary"] });
    },
    onError,
  });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;
  const s = summary.data;
  const chips: { key: HealthKind; text: string; n?: number; warn?: boolean }[] = [
    { key: "stuck", text: j.stuck, n: s?.stuck, warn: !!s?.stuck },
    { key: "failed", text: j.failed, n: s?.failed_7d, warn: !!s?.failed_7d },
    { key: "running", text: j.running, n: s?.running },
  ];

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{j.hint}</p>
      <Card>
        <CardContent className="space-y-4 p-4">
          <div className="flex flex-wrap gap-2">
            {chips.map((c) => (
              <Button
                key={c.key}
                size="sm"
                variant={kind === c.key ? "default" : "outline"}
                onClick={() => {
                  setKind(c.key);
                  setPage(1);
                }}
              >
                {c.text}
                {c.n !== undefined ? <span className={cn("tabular-nums", kind !== c.key && c.warn && "text-rose-700 dark:text-rose-300")}>({c.n})</span> : null}
              </Button>
            ))}
          </div>
          {kind === "failed" ? <p className="text-xs text-muted-foreground">{j.failedHint}</p> : null}
          {q.isLoading ? (
            <LoadingState rows={4} />
          ) : q.error ? (
            <ErrorState error={q.error} onRetry={() => q.refetch()} />
          ) : !q.data?.items.length ? (
            <EmptyState title={j.empty[kind]} />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <thead>
                  <tr>
                    <Th>{j.colSearch}</Th>
                    <Th>{j.colWorkspace}</Th>
                    <Th>{j.colStatus}</Th>
                    <Th>{j.colActivity}</Th>
                    <Th>{j.colCost}</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {q.data.items.map((r) => {
                    const active = ACTIVE.includes(r.status);
                    return (
                      <tr key={r.id}>
                        <Td>
                          <p className="font-medium">{r.name}</p>
                          <p className="text-xs text-muted-foreground">
                            {r.run_number ? j.run.replace("{n}", String(r.run_number)) : null}
                            {r.origin === "telegram" ? <Send className="ms-1 inline size-3" aria-label="Telegram" /> : null}
                          </p>
                          {r.last_error ? (
                            <p className="mt-1 max-w-80 text-xs text-destructive" title={r.last_error}>
                              <AlertTriangle className="me-1 inline size-3" aria-hidden />
                              <span className="line-clamp-2">{r.last_error}</span>
                            </p>
                          ) : null}
                        </Td>
                        <Td>
                          <p className="text-sm">{r.workspace_name}</p>
                          <p className="text-xs text-muted-foreground" dir="ltr">{r.owner_email ?? "—"}</p>
                        </Td>
                        <Td>
                          <div className="flex flex-col items-start gap-1">
                            <Badge tone={r.status === "failed" ? "red" : r.status === "partially_completed" ? "yellow" : "blue"}>{label(r.status)}</Badge>
                            {r.stuck ? <Badge tone="red">{j.stuckBadge}</Badge> : null}
                            <span className="text-[11px] text-muted-foreground">{label(r.stage)}</span>
                          </div>
                        </Td>
                        <Td className="whitespace-nowrap text-xs">
                          <p>{formatDate(r.last_activity_at, locale)}</p>
                          <p className="text-muted-foreground">{j.started} {formatDate(r.started_at, locale)}</p>
                        </Td>
                        <Td className="tabular-nums text-xs" dir="ltr">${r.cost_usd.toFixed(2)}</Td>
                        <Td>
                          <div className="flex flex-wrap gap-1.5">
                            {r.stuck ? (
                              <Button size="sm" disabled={act.isPending} onClick={() => act.mutate({ id: r.id, action: "requeue" })}>
                                <RotateCcw /> {j.requeue}
                              </Button>
                            ) : null}
                            {!active ? (
                              <Button size="sm" variant="outline" disabled={act.isPending} onClick={() => act.mutate({ id: r.id, action: "retry" })}>
                                <RotateCcw /> {j.retry}
                              </Button>
                            ) : null}
                            {active ? (
                              <Button
                                size="sm"
                                variant="ghost"
                                className="text-destructive"
                                disabled={act.isPending}
                                onClick={() => window.confirm(j.cancelConfirm.replace("{name}", r.name)) && act.mutate({ id: r.id, action: "cancel" })}
                              >
                                <Ban /> {j.cancel}
                              </Button>
                            ) : null}
                          </div>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
            </div>
          )}
          <Pager page={page} pages={pages} onPage={setPage} />
        </CardContent>
      </Card>
    </div>
  );
}
