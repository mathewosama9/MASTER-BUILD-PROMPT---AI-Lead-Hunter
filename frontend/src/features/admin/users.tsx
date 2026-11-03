"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Search } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, Input, Select, Table, Td, Th } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { countryFlag, countryName } from "@/lib/countries";
import { cn, formatDate, formatNumber } from "@/lib/utils";
import type { Page } from "@/types/api";

import { CsvButton } from "./ops";
import { APPROVAL_TONE, LastSeen, PlanBadge, TelegramBadge, UserDialog, type UserRow } from "./user-dialog";

interface Summary {
  total: number;
  pending: number;
  suspicious: number;
  suspicious_pending: number;
  rejected: number;
  new_7d: number;
  telegram_linked: number;
}

type Filter = "all" | "pending" | "suspicious" | "approved" | "rejected";
type TelegramFilter = "" | "linked" | "unlinked";

function initialUser(): string | null {
  return typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("user");
}

export function UsersAdmin() {
  const { t, locale } = useI18n();
  const u = t.admin.users;
  const [filter, setFilter] = useState<Filter>("pending");
  const [search, setSearch] = useState("");
  const [tg, setTg] = useState<TelegramFilter>("");
  const [page, setPage] = useState(1);
  // A Telegram or bell link opens one user directly: /app/admin?tab=users&user=<id>
  const [open, setOpen] = useState<string | null>(initialUser);
  const summary = useQuery({ queryKey: ["admin-users-summary"], queryFn: () => api<Summary>("/admin/users/summary") });
  const q = useQuery({
    queryKey: ["admin-users", filter, search, tg, page],
    queryFn: () =>
      api<Page<UserRow>>("/admin/users", {
        query: {
          q: search || undefined,
          status: filter === "pending" || filter === "approved" || filter === "rejected" ? filter : undefined,
          suspicious: filter === "suspicious" ? true : undefined,
          telegram: tg ? tg === "linked" : undefined,
          page,
          page_size: 25,
        },
      }),
  });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;
  const s = summary.data;
  const chips: { key: Filter; text: string; n?: number; tone?: string }[] = [
    { key: "pending", text: u.pending, n: s?.pending, tone: "text-[#7a5700] dark:text-sun-400" },
    { key: "suspicious", text: u.suspicious, n: s?.suspicious, tone: "text-rose-700 dark:text-rose-300" },
    { key: "approved", text: u.approved },
    { key: "rejected", text: u.rejected, n: s?.rejected },
    { key: "all", text: u.all, n: s?.total },
  ];

  return (
    <div className="space-y-4">
      {s ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Stat label={u.summaryPending} value={s.pending} warn={s.pending > 0} />
          <Stat label={u.summarySuspicious} value={s.suspicious} hint={u.waitingOf.replace("{n}", String(s.suspicious_pending))} warn={s.suspicious_pending > 0} />
          <Stat label={u.summaryTotal} value={s.total} hint={u.newThisWeek.replace("{n}", String(s.new_7d))} />
          <Stat label={u.summaryRejected} value={s.rejected} />
          <Stat label={u.summaryTelegram} value={s.telegram_linked} hint={u.telegramOf.replace("{n}", String(s.total - s.telegram_linked))} />
        </div>
      ) : null}
      <Card>
        <CardContent className="space-y-4 p-4">
          <div className="flex flex-wrap items-center gap-2">
            {chips.map((c) => (
              <Button
                key={c.key}
                size="sm"
                variant={filter === c.key ? "default" : "outline"}
                onClick={() => {
                  setFilter(c.key);
                  setPage(1);
                }}
              >
                {c.text}
                {c.n !== undefined ? <span className={cn("tabular-nums", filter !== c.key && c.n > 0 && c.tone)}>({c.n})</span> : null}
              </Button>
            ))}
            <Select
              aria-label={u.telegram}
              className="h-8 w-auto"
              value={tg}
              onChange={(e) => {
                setTg(e.target.value as TelegramFilter);
                setPage(1);
              }}
            >
              <option value="">{u.telegram}: {u.all}</option>
              <option value="linked">{u.tgLinked}</option>
              <option value="unlinked">{u.tgNone}</option>
            </Select>
            <CsvButton
              path="/admin/exports/users.csv"
              query={{
                q: search || undefined,
                status: filter === "pending" || filter === "approved" || filter === "rejected" ? filter : undefined,
                suspicious: filter === "suspicious" ? true : undefined,
                telegram: tg ? tg === "linked" : undefined,
              }}
            />
            <div className="relative ms-auto w-full sm:w-72">
              <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input
                aria-label={u.search}
                placeholder={u.search}
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
            <LoadingState rows={5} />
          ) : q.error ? (
            <ErrorState error={q.error} onRetry={() => q.refetch()} />
          ) : !q.data?.items.length ? (
            <EmptyState title={u.empty} />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <thead>
                  <tr>
                    <Th>{u.colUser}</Th>
                    <Th>{u.nationality}</Th>
                    <Th>{u.colWorkspace}</Th>
                    <Th>{t.billing.balance}</Th>
                    <Th>{u.colStatus}</Th>
                    <Th>{u.telegram}</Th>
                    <Th>{u.lastSeen}</Th>
                    <Th>{u.created}</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {q.data.items.map((r) => (
                    <tr
                      key={r.id}
                      className={cn("cursor-pointer hover:bg-muted/50", (r.approval_status === "rejected" || !r.is_active) && "opacity-60")}
                      onClick={() => setOpen(r.id)}
                    >
                      <Td>
                        <p className="font-medium">
                          {r.full_name || "—"}
                          {r.is_superuser ? <Badge tone="indigo" className="ms-2">{u.superuser}</Badge> : null}
                        </p>
                        <p className="text-xs text-muted-foreground" dir="ltr">{r.email}</p>
                        {r.phone ? <p className="text-xs text-muted-foreground" dir="ltr">{r.phone}</p> : null}
                      </Td>
                      <Td className="whitespace-nowrap text-sm">
                        {r.nationality ? `${countryFlag(r.nationality)} ${countryName(r.nationality, locale)}` : "—"}
                      </Td>
                      <Td>
                        <p className="text-sm">{r.workspace?.name ?? "—"}</p>
                        {r.workspace ? <PlanBadge w={r.workspace} /> : null}
                      </Td>
                      <Td className="tabular-nums">{r.workspace?.billing_exempt ? "∞" : formatNumber(r.workspace?.balance ?? 0, locale)}</Td>
                      <Td>
                        <div className="flex flex-col items-start gap-1">
                          <Badge tone={APPROVAL_TONE[r.approval_status]}>{u.status[r.approval_status]}</Badge>
                          {r.matches ? (
                            <Badge tone={r.strong_matches ? "red" : "yellow"}>
                              <AlertTriangle className="size-3" aria-hidden /> {u.matches.replace("{n}", String(r.matches))}
                            </Badge>
                          ) : null}
                          {!r.is_active ? <Badge tone="red">{u.deactivated}</Badge> : null}
                          {!r.email_verified_at ? <span className="text-[11px] text-muted-foreground">{u.notVerified}</span> : null}
                        </div>
                      </Td>
                      <Td>
                        <TelegramBadge state={r.telegram_status} username={r.telegram_username} />
                      </Td>
                      <Td className="whitespace-nowrap text-xs">
                        <LastSeen at={r.last_seen_at ?? r.last_login_at} />
                      </Td>
                      <Td className="whitespace-nowrap text-xs">{formatDate(r.created_at, locale)}</Td>
                      <Td>
                        <Button size="sm" variant="ghost" onClick={() => setOpen(r.id)}>{u.details}</Button>
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
      </Card>
      {open ? <UserDialog key={open} id={open} onOpen={setOpen} onClose={() => setOpen(null)} /> : null}
    </div>
  );
}

function Stat({ label, value, hint, warn }: { label: string; value: number; hint?: string; warn?: boolean }) {
  return (
    <Card className={cn(warn && "border-sun-500/60")}>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
        {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}
