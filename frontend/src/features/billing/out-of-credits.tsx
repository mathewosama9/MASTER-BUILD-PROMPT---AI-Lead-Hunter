"use client";

import { AlertTriangle, Coins } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useBillingSummary } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { cn, formatNumber } from "@/lib/utils";

type Reason = "empty" | "trial" | "stopped" | "low";

/**
 * The one "top up" prompt for every dead end: zero balance, an ended trial, a search stopped for lack of credits,
 * or (opt-in) a low balance. Renders nothing for metered-off workspaces or when there is nothing to say, so it can
 * be dropped anywhere. Pass `stopped` from a campaign that halted on credits to force that message.
 */
export function OutOfCredits({ stopped, warnLow, className }: { stopped?: boolean; warnLow?: boolean; className?: string }) {
  const { t, locale } = useI18n();
  const { data: s } = useBillingSummary();
  if (!s || s.billing_exempt || s.awaiting_verification || s.awaiting_approval) return null;
  const reason: Reason | null = stopped
    ? "stopped"
    : s.on_trial && s.trial_expired
      ? "trial"
      : s.balance <= 0
        ? "empty"
        : warnLow && s.low_balance
          ? "low"
          : null;
  if (!reason) return null;
  const o = t.outOfCredits;
  const copy = {
    empty: [o.emptyTitle, o.emptyBody],
    trial: [o.trialTitle, o.trialBody],
    stopped: [o.stoppedTitle, o.stoppedBody],
    low: [o.lowTitle, o.lowBody.replace("{n}", formatNumber(s.balance, locale))],
  }[reason];
  const soft = reason === "low";
  return (
    <div
      role={soft ? "status" : "alert"}
      className={cn(
        "flex flex-col gap-4 rounded-2xl border p-5 sm:flex-row sm:items-center",
        soft ? "border-sun-500/50 bg-sun-100/60 dark:bg-sun-500/10" : "border-ink-900 bg-ink-900 text-paper",
        className,
      )}
    >
      <span
        className={cn(
          "flex size-11 shrink-0 items-center justify-center rounded-xl",
          soft ? "bg-sun-200 text-[#7a5700] dark:bg-sun-500/20 dark:text-sun-400" : "bg-white/10 text-signal-400",
        )}
      >
        {soft ? <AlertTriangle className="size-5" aria-hidden /> : <Coins className="size-5" aria-hidden />}
      </span>
      <div className="flex-1">
        <p className="font-semibold">{copy[0]}</p>
        <p className={cn("mt-1 text-sm", soft ? "text-muted-foreground" : "text-mist-300")}>{copy[1]}</p>
      </div>
      <Button asChild variant={soft ? "ink" : "accent"}>
        <Link href="/app/billing">{o.cta}</Link>
      </Button>
    </div>
  );
}
