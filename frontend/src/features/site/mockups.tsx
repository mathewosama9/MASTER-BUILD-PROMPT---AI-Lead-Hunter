"use client";

import { BadgeCheck, Check, Globe, Mail, MessageCircle, Phone, Sparkles, UserRound } from "lucide-react";

import { useI18n } from "@/i18n/provider";
import { cn } from "@/lib/utils";

import { Ping } from "./motion";

// Illustrations of the product drawn in code. Names and numbers are examples, labelled as such on the page.

const SCORES = [92, 88, 81, 76];

function contactIcon(i: number) {
  return i === 1 ? Phone : i === 3 ? Mail : MessageCircle;
}

export function ScoreBadge({ score, className }: { score: number; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 min-w-9 items-center justify-center rounded-md px-1.5 text-xs font-bold tabular-nums",
        score >= 85 ? "bg-signal-400 text-ink-900" : score >= 75 ? "bg-rasd-500/20 text-rasd-300" : "bg-white/10 text-mist-300",
        className,
      )}
    >
      {score}
    </span>
  );
}

/** The leads table in a dark app window. */
export function LeadsTableMockup({ className }: { className?: string }) {
  const { t } = useI18n();
  const m = t.site.mockup;
  return (
    <div className={cn("overflow-hidden rounded-2xl border border-white/10 bg-ink-900 text-paper shadow-2xl shadow-ink-900/30", className)}>
      <div className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
        <span className="size-2.5 rounded-full bg-white/15" />
        <span className="size-2.5 rounded-full bg-white/15" />
        <span className="size-2.5 rounded-full bg-white/15" />
        <span className="ms-3 text-xs text-mist-300">{m.window}</span>
        <span className="ms-auto inline-flex items-center gap-2 rounded-full bg-white/5 px-2.5 py-1 text-[11px] text-mist-300">
          <Ping className="size-2" /> {m.scanning}
        </span>
      </div>
      <div className="flex flex-wrap items-end justify-between gap-3 px-5 pb-3 pt-5">
        <div>
          <p className="text-[11px] text-mist-300">{t.site.example}</p>
          <p className="font-display text-base font-semibold">{m.campaign}</p>
        </div>
        <div className="flex gap-4 text-end">
          <div>
            <p className="font-display text-xl font-bold tabular-nums">148</p>
            <p className="text-[11px] text-mist-300">{m.found}</p>
          </div>
          <div>
            <p className="font-display text-xl font-bold tabular-nums text-signal-400">63</p>
            <p className="text-[11px] text-mist-300">{m.ready}</p>
          </div>
        </div>
      </div>
      <div className="px-3 pb-3">
        <div className="grid grid-cols-[1fr_auto_auto] gap-x-4 px-2 py-2 text-[11px] text-mist-300">
          <span>{m.columns.business}</span>
          <span>{m.columns.contact}</span>
          <span>{m.columns.score}</span>
        </div>
        <ul className="space-y-1.5">
          {m.rows.map((r, i) => {
            const Icon = contactIcon(i);
            return (
              <li
                key={r.name}
                className={cn(
                  "grid grid-cols-[1fr_auto_auto] items-center gap-x-4 rounded-xl px-2 py-2.5",
                  i === 0 ? "bg-white/[0.07] ring-1 ring-signal-400/30" : "bg-white/[0.03]",
                )}
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{r.name}</p>
                  <p className="truncate text-[11px] text-mist-300">{r.city}</p>
                </div>
                <span className="inline-flex items-center gap-1 text-[11px] text-rasd-300">
                  <Icon className="size-3.5" aria-hidden /> <span className="hidden sm:inline">{r.contact}</span>
                </span>
                <ScoreBadge score={SCORES[i] ?? 70} />
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

/** "Why they need you" card. */
export function WhyCardMockup({ className }: { className?: string }) {
  const { t } = useI18n();
  const m = t.site.mockup;
  return (
    <div className={cn("rounded-2xl border bg-card p-4 text-card-foreground shadow-xl shadow-ink-900/10", className)}>
      <p className="flex items-center gap-1.5 text-xs font-semibold text-rasd-700 dark:text-rasd-300">
        <Sparkles className="size-3.5" aria-hidden /> {m.whyTitle}
      </p>
      <ul className="mt-3 space-y-2">
        {m.why.map((w) => (
          <li key={w} className="flex gap-2 text-sm leading-snug">
            <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full bg-rasd-600 text-white">
              <Check className="size-2.5" aria-hidden />
            </span>
            {w}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The decision-maker found for a lead: name, role and direct channels. */
export function DecisionMakerMockup({ className }: { className?: string }) {
  const { t } = useI18n();
  const m = t.site.mockup;
  const channels = [
    { icon: Phone, label: m.dmDirect, value: "+966 5• ••• 4821" },
    { icon: MessageCircle, label: "WhatsApp", value: "+966 5• ••• 4821" },
    { icon: Mail, label: "Email", value: "k.otaibi@•••.sa" },
    { icon: Globe, label: "LinkedIn", value: "linkedin.com/in/•••" },
  ];
  return (
    <div className={cn("rounded-2xl border bg-card p-5 text-card-foreground shadow-xl shadow-ink-900/10", className)}>
      <p className="flex items-center gap-1.5 text-xs font-semibold text-rasd-700 dark:text-rasd-300">
        <UserRound className="size-3.5" aria-hidden /> {m.dmTitle}
      </p>
      <div className="mt-3 flex items-center gap-3">
        <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-ink-900 font-display font-semibold text-signal-400">
          {m.dmName.replace(/^(Dr\.|د\.)\s*/, "").slice(0, 1)}
        </span>
        <div className="min-w-0">
          <p className="truncate font-display font-semibold">{m.dmName}</p>
          <p className="truncate text-sm text-muted-foreground">
            {m.dmRole} · {m.rows[0].name}
          </p>
        </div>
      </div>
      <ul className="mt-4 space-y-2">
        {channels.map((c) => (
          <li key={c.label} className="flex items-center gap-3 rounded-xl bg-muted/60 px-3 py-2 text-sm">
            <c.icon className="size-4 shrink-0 text-rasd-600" aria-hidden />
            <span className="w-24 shrink-0 text-xs text-muted-foreground">{c.label}</span>
            <span className="truncate font-medium tabular-nums" dir="ltr">
              {c.value}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-rasd-100 px-2.5 py-1 text-xs font-medium text-rasd-800 dark:bg-rasd-500/15 dark:text-rasd-200">
        <BadgeCheck className="size-3.5" aria-hidden /> {m.dmConfidence}
      </p>
    </div>
  );
}

/** A ready first message as a WhatsApp-style bubble. */
export function MessageMockup({ className, text }: { className?: string; text?: string }) {
  const { t } = useI18n();
  const m = t.site.mockup;
  return (
    <div className={cn("rounded-2xl border bg-card p-4 text-card-foreground shadow-xl shadow-ink-900/10", className)}>
      <p className="text-xs font-semibold text-muted-foreground">{m.messageTitle}</p>
      <p className="mt-2 rounded-2xl rounded-ss-sm bg-[#dcf8c6] p-3 text-sm leading-relaxed text-ink-900">{text ?? m.message}</p>
      <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-[#25d366] px-3 py-1.5 text-xs font-semibold text-white">
        <MessageCircle className="size-3.5" aria-hidden /> {m.openWhatsapp}
      </p>
    </div>
  );
}

/** Hero composition: the table with the analysis and message cards floating over it. */
export function HeroMockup() {
  return (
    <div className="relative mx-auto w-full max-w-xl pb-28 lg:pb-16">
      <LeadsTableMockup />
      <WhyCardMockup className="absolute -bottom-2 start-[-0.5rem] w-64 sm:start-[-2rem] lg:-bottom-6" />
      <MessageMockup className="absolute -bottom-10 end-[-0.5rem] hidden w-64 sm:block sm:end-[-1.5rem] lg:-bottom-20" />
    </div>
  );
}
