"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck, Megaphone, Radar, Settings, ShieldCheck, Wallet } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Popover as RPopover } from "radix-ui";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useNotificationBell } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn, relativeTime } from "@/lib/utils";
import type { NotificationItem } from "@/types/api";

function KindIcon({ kind }: { kind: string }) {
  const props = { className: "size-4", "aria-hidden": true } as const;
  if (kind.startsWith("campaign_")) return <Radar {...props} />;
  if (/^(credits|payment|topup|trial)_/.test(kind)) return <Wallet {...props} />;
  if (kind === "announcement" || kind === "marketing") return <Megaphone {...props} />;
  return <ShieldCheck {...props} />;
}

/** Open a notification: mark it read, then follow its link. Shared by the bell and the notifications page. */
export function useOpenNotification() {
  const qc = useQueryClient();
  const router = useRouter();
  return async (n: NotificationItem) => {
    if (!n.read_at) {
      await api(`/notifications/${n.id}/read`, { method: "POST" }).catch(() => undefined);
      void qc.invalidateQueries({ queryKey: ["notifications"] });
    }
    if (!n.link) return;
    if (n.link.startsWith("/") && !n.link.startsWith("//")) router.push(n.link);
    else if (n.link.startsWith("https://")) window.open(n.link, "_blank", "noopener,noreferrer");
  };
}

export function NotificationRow({ n, onOpen, compact = false }: { n: NotificationItem; onOpen: (n: NotificationItem) => void; compact?: boolean }) {
  const { locale } = useI18n();
  return (
    <button
      type="button"
      onClick={() => onOpen(n)}
      className={cn(
        "flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-start transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        !n.read_at && "bg-rasd-50/70 dark:bg-rasd-700/10",
      )}
    >
      <span className={cn("mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full", n.read_at ? "bg-muted text-muted-foreground" : "bg-ink-900 text-signal-400")}>
        <KindIcon kind={n.kind} />
      </span>
      <span className="min-w-0 flex-1">
        <span className={cn("block text-sm leading-snug", !n.read_at && "font-semibold")}>{n.title}</span>
        {n.body ? <span className={cn("mt-0.5 block whitespace-pre-line text-xs text-muted-foreground", compact && "line-clamp-2")}>{n.body}</span> : null}
        <span className="mt-1 block text-[11px] text-muted-foreground">{relativeTime(n.created_at, locale)}</span>
      </span>
      {!n.read_at ? <span aria-hidden className="mt-2 size-2 shrink-0 rounded-full bg-signal-500" /> : null}
    </button>
  );
}

export function NotificationBell() {
  const { t, locale } = useI18n();
  const qc = useQueryClient();
  const { data } = useNotificationBell();
  const [open, setOpen] = useState(false);
  const openNotification = useOpenNotification();
  const unread = data?.unread ?? 0;

  // A toast when something new arrives while the dashboard is open (not for what was already there).
  const seen = useRef<string | null>(null);
  useEffect(() => {
    const newest = data?.items[0];
    if (!newest) return;
    if (seen.current !== null && newest.id !== seen.current && !newest.read_at) toast(newest.title, { description: newest.body.slice(0, 140) });
    seen.current = newest.id;
  }, [data]);

  async function readAll() {
    await api("/notifications/read-all", { method: "POST" }).catch(() => undefined);
    void qc.invalidateQueries({ queryKey: ["notifications"] });
  }

  const label = unread ? `${t.notify.bell} · ${t.notify.unread.replace("{n}", String(unread))}` : t.notify.bell;
  return (
    <RPopover.Root open={open} onOpenChange={setOpen}>
      <RPopover.Trigger
        aria-label={label}
        className="relative flex size-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Bell className="size-5" />
        {unread ? (
          <span className="absolute -end-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-signal-400 px-1 text-[10px] font-bold tabular-nums text-ink-900 ring-2 ring-background">
            {unread > 99 ? "99+" : unread}
          </span>
        ) : null}
      </RPopover.Trigger>
      <RPopover.Portal>
        <RPopover.Content
          align="end"
          sideOffset={8}
          dir={locale === "ar" ? "rtl" : "ltr"}
          className="z-50 flex max-h-[70vh] w-[min(24rem,calc(100vw-1.5rem))] flex-col rounded-xl border bg-card text-card-foreground shadow-xl"
        >
          <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
            <p className="text-sm font-semibold">
              {t.notify.bell}
              {unread ? <span className="ms-2 text-xs font-normal text-muted-foreground">{t.notify.unread.replace("{n}", String(unread))}</span> : null}
            </p>
            {unread ? (
              <button type="button" onClick={() => void readAll()} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                <CheckCheck className="size-3.5" aria-hidden /> {t.notify.markAllRead}
              </button>
            ) : null}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
            {data?.items.length ? (
              data.items.map((n) => (
                <NotificationRow
                  key={n.id}
                  n={n}
                  compact
                  onOpen={(x) => {
                    setOpen(false);
                    void openNotification(x);
                  }}
                />
              ))
            ) : (
              <p className="px-4 py-8 text-center text-sm text-muted-foreground">{t.notify.empty}</p>
            )}
          </div>
          <div className="flex items-center justify-between gap-2 border-t px-4 py-2.5 text-xs">
            <Link href="/app/notifications" onClick={() => setOpen(false)} className="font-medium hover:underline">
              {t.notify.viewAll}
            </Link>
            <Link href="/app/settings?tab=notifications" onClick={() => setOpen(false)} className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
              <Settings className="size-3.5" aria-hidden /> {t.notify.settingsLink}
            </Link>
          </div>
        </RPopover.Content>
      </RPopover.Portal>
    </RPopover.Root>
  );
}
