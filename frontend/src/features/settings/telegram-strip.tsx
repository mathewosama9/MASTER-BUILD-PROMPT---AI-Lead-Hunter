"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Hourglass, Send } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";

export type LinkCode = { code: string; expires_at: string; bot_username: string | null; deep_link: string | null };

/** While a link code is live, re-check the account every few seconds so the page updates as soon as the bot links it. */
export function useWatchTelegramLink(until: number | null, onExpired?: () => void) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!until) return;
    const id = window.setInterval(() => {
      if (Date.now() > until) {
        window.clearInterval(id);
        onExpired?.();
        return;
      }
      void qc.invalidateQueries({ queryKey: ["me"] });
      void qc.invalidateQueries({ queryKey: ["tg-accounts"] });
    }, 4000);
    return () => window.clearInterval(id);
  }, [until, onExpired, qc]);
}

/** Sticky strip on every dashboard page until the signed-in user links Telegram. */
export function TelegramStrip({ status }: { status: "pending" | "none" }) {
  const { t } = useI18n();
  const router = useRouter();
  const [until, setUntil] = useState<number | null>(null);
  useWatchTelegramLink(until, useCallback(() => setUntil(null), []));
  const link = useMutation({
    mutationFn: () => api<LinkCode>("/telegram/link-code", { method: "POST" }),
    onSuccess: (c) => {
      if (!c.deep_link) {
        router.push("/app/settings?tab=telegram");
        return;
      }
      setUntil(Date.parse(c.expires_at));
      // Opened after an await, so a popup blocker may refuse the new tab: fall back to this tab.
      if (!window.open(c.deep_link, "_blank", "noopener,noreferrer")) window.location.href = c.deep_link;
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-sky-500/30 bg-sky-500/10 px-4 py-2 text-xs text-foreground md:px-6">
      {status === "pending" ? (
        <Hourglass className="size-4 text-sky-500" aria-hidden />
      ) : (
        <Send className="size-4 text-sky-500" aria-hidden />
      )}
      <span className="min-w-0 flex-1">{status === "pending" ? t.settings.tgStripPending : t.settings.tgStrip}</span>
      {status === "none" ? (
        until ? (
          <span role="status" className="flex items-center gap-1.5 text-muted-foreground">
            <Spinner /> {t.settings.tgStripWaiting}
          </span>
        ) : (
          <Button size="sm" className="h-7" onClick={() => link.mutate()} disabled={link.isPending}>
            {link.isPending ? <Spinner /> : <Send />} {t.settings.tgStripCta}
          </Button>
        )
      ) : null}
    </div>
  );
}
