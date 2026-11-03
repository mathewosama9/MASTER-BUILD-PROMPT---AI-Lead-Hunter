"use client";

import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck, Settings } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { NotificationPage } from "@/types/api";

import { NotificationRow, useOpenNotification } from "./bell";

const PAGE_SIZE = 30;

export function NotificationsPage() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const open = useOpenNotification();
  const q = useInfiniteQuery({
    queryKey: ["notifications", "page", unreadOnly],
    queryFn: ({ pageParam }) => api<NotificationPage>("/notifications", { query: { page: pageParam, limit: PAGE_SIZE, unread: unreadOnly || undefined } }),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (pages.length * PAGE_SIZE < last.total ? pages.length + 1 : undefined),
  });
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  const unread = q.data?.pages[0]?.unread ?? 0;

  async function readAll() {
    await api("/notifications/read-all", { method: "POST" });
    void qc.invalidateQueries({ queryKey: ["notifications"] });
  }

  const filter = (on: boolean, text: string) => (
    <button
      type="button"
      onClick={() => setUnreadOnly(on)}
      aria-pressed={unreadOnly === on}
      className={cn(
        "rounded-full px-3 py-1 text-sm transition-colors",
        unreadOnly === on ? "bg-ink-900 text-paper dark:bg-paper dark:text-ink-900" : "text-muted-foreground hover:bg-muted",
      )}
    >
      {text}
    </button>
  );

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title={t.notify.pageTitle}
        subtitle={t.notify.pageSubtitle}
        actions={
          <>
            {unread ? (
              <Button variant="outline" size="sm" onClick={() => void readAll()}>
                <CheckCheck /> {t.notify.markAllRead}
              </Button>
            ) : null}
            <Button asChild variant="ghost" size="sm">
              <Link href="/app/settings?tab=notifications">
                <Settings /> {t.notify.settingsLink}
              </Link>
            </Button>
          </>
        }
      />
      <div className="mb-3 flex gap-1">
        {filter(false, t.notify.filterAll)}
        {filter(true, `${t.notify.filterUnread}${unread ? ` (${unread})` : ""}`)}
      </div>
      {q.isLoading ? (
        <LoadingState />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : !items.length ? (
        <EmptyState title={t.notify.empty} />
      ) : (
        <Card className="p-1.5">
          {items.map((n) => (
            <NotificationRow key={n.id} n={n} onOpen={(x) => void open(x)} />
          ))}
          {q.hasNextPage ? (
            <div className="p-2 text-center">
              <Button variant="ghost" size="sm" disabled={q.isFetchingNextPage} onClick={() => void q.fetchNextPage()}>
                {t.notify.loadMore}
              </Button>
            </div>
          ) : null}
        </Card>
      )}
    </div>
  );
}
