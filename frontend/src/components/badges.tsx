"use client";

import { FlaskConical } from "lucide-react";

import { Badge, type BadgeTone } from "@/components/ui/primitives";
import { useI18n } from "@/i18n/provider";
import type { CampaignStatus } from "@/types/api";

const STATUS_TONE: Record<CampaignStatus, BadgeTone> = {
  draft: "neutral",
  queued: "indigo",
  discovering: "blue",
  enriching: "blue",
  analyzing: "blue",
  completed: "green",
  partially_completed: "yellow",
  failed: "red",
  paused: "yellow",
  cancelled: "neutral",
};

export function StatusBadge({ status }: { status: CampaignStatus }) {
  const { t } = useI18n();
  const running = ["queued", "discovering", "enriching", "analyzing"].includes(status);
  return (
    <Badge tone={STATUS_TONE[status] ?? "neutral"}>
      {running ? <span className="size-1.5 animate-pulse rounded-full bg-current" aria-hidden /> : null}
      {t.status[status] ?? status}
    </Badge>
  );
}

const PRIORITY_TONE: Record<string, BadgeTone> = { high: "yellow", medium: "blue", low: "neutral", needs_review: "indigo" };

export function PriorityBadge({ priority }: { priority: string | null }) {
  const { t } = useI18n();
  if (!priority) return <span className="text-muted-foreground">—</span>;
  return <Badge tone={PRIORITY_TONE[priority] ?? "neutral"}>{t.priority[priority as keyof typeof t.priority] ?? priority}</Badge>;
}

const VERIFY_TONE: Record<string, BadgeTone> = {
  verified: "green",
  invalid: "red",
  restricted: "red",
  discovered: "blue",
  unverified: "neutral",
  unknown: "neutral",
};

export function VerificationBadge({ status }: { status: string }) {
  const { t } = useI18n();
  return <Badge tone={VERIFY_TONE[status] ?? "neutral"}>{t.verification[status as keyof typeof t.verification] ?? status}</Badge>;
}

const PROVIDER_TONE: Record<string, BadgeTone> = {
  connected: "green",
  requires_api_key: "yellow",
  requires_permission: "yellow",
  unsupported: "neutral",
  disabled: "neutral",
  rate_limited: "red",
  error: "red",
};

export function ProviderStatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  return (
    <Badge tone={PROVIDER_TONE[status] ?? "neutral"}>
      {t.providerStatus[status as keyof typeof t.providerStatus] ?? status}
    </Badge>
  );
}

export function DemoBadge() {
  const { t } = useI18n();
  return (
    <Badge tone="yellow" className="uppercase tracking-wide">
      <FlaskConical className="size-3" aria-hidden />
      {t.common.demoMode}
    </Badge>
  );
}

export function ScorePill({ score }: { score: number | null }) {
  if (score === null || score === undefined) return <span className="text-muted-foreground">—</span>;
  const tone = score >= 70 ? "bg-sun-500 text-navy-900" : score >= 50 ? "bg-brand-500 text-white" : "bg-muted text-muted-foreground";
  return (
    <span className={`inline-flex min-w-10 justify-center rounded-md px-1.5 py-0.5 text-xs font-semibold tabular-nums ${tone}`}>
      {Math.round(score)}
    </span>
  );
}
