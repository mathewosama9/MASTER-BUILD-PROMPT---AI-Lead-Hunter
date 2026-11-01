"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, Download, Pause, Play, RotateCcw, Square, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Tip } from "@/components/ui/primitives";
import { useI18n } from "@/i18n/provider";
import { api, download } from "@/lib/api";
import type { Campaign } from "@/types/api";

import { ACTIVE } from "@/hooks/queries";

export function CampaignActions({ c, compact = false }: { c: Campaign; compact?: boolean }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const router = useRouter();
  const act = useMutation({
    mutationFn: (action: string) =>
      action === "delete"
        ? api(`/campaigns/${c.id}`, { method: "DELETE" })
        : api<Campaign>(`/campaigns/${c.id}/${action}`, { method: "POST" }),
    onSuccess: (res, action) => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      qc.invalidateQueries({ queryKey: ["campaign", c.id] });
      qc.invalidateQueries({ queryKey: ["campaign-events", c.id] });
      if (action === "duplicate" && res && typeof res === "object" && "id" in res) router.push(`/app/campaigns/${(res as Campaign).id}`);
      if (action === "delete") router.push("/app/campaigns");
      toast.success(`${buttons.find((b) => b.key === action)?.label ?? (action === "delete" ? t.campaigns.delete : t.common.done)} ✓`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const running = ACTIVE.includes(c.status);
  const buttons: { key: string; label: string; icon: React.ReactNode; show: boolean; variant?: "default" | "outline" | "destructive" | "accent" }[] = [
    { key: "start", label: t.campaigns.start, icon: <Play />, show: c.status === "draft", variant: "accent" },
    { key: "pause", label: t.campaigns.pause, icon: <Pause />, show: running },
    { key: "resume", label: t.campaigns.resume, icon: <Play />, show: c.status === "paused", variant: "accent" },
    { key: "cancel", label: t.campaigns.cancelRun, icon: <Square />, show: running || c.status === "paused" || c.status === "draft" },
    { key: "retry", label: t.campaigns.retry, icon: <RotateCcw />, show: ["failed", "partially_completed", "cancelled"].includes(c.status) },
    { key: "duplicate", label: t.campaigns.duplicate, icon: <Copy />, show: true },
  ];

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {buttons
        .filter((b) => b.show)
        .map((b) =>
          compact ? (
            <Tip key={b.key} content={b.label}>
              <Button size="icon" variant="ghost" aria-label={b.label} disabled={act.isPending} onClick={() => act.mutate(b.key)}>
                {b.icon}
              </Button>
            </Tip>
          ) : (
            <Button key={b.key} size="sm" variant={b.variant ?? "outline"} disabled={act.isPending} onClick={() => act.mutate(b.key)}>
              {b.icon} {b.label}
            </Button>
          ),
        )}
      {compact ? (
        <Tip content={t.campaigns.exportResults}>
          <Button
            size="icon"
            variant="ghost"
            aria-label={t.campaigns.exportResults}
            onClick={() => download(`/exports/campaigns/${c.id}`, { format: "xlsx" }).catch((e) => toast.error(e.message))}
          >
            <Download />
          </Button>
        </Tip>
      ) : (
        <>
          <Button size="sm" variant="outline" onClick={() => download(`/exports/campaigns/${c.id}`, { format: "csv" }).catch((e) => toast.error(e.message))}>
            <Download /> CSV
          </Button>
          <Button size="sm" variant="outline" onClick={() => download(`/exports/campaigns/${c.id}`, { format: "xlsx" }).catch((e) => toast.error(e.message))}>
            <Download /> {t.monitor.xlsxReport}
          </Button>
        </>
      )}
      {!running ? (
        <Tip content={t.campaigns.delete}>
          <Button
            size="icon"
            variant="ghost"
            aria-label={t.campaigns.delete}
            onClick={() => window.confirm(`${t.campaigns.delete}: ${c.name}?`) && act.mutate("delete")}
          >
            <Trash2 className="text-destructive" />
          </Button>
        </Tip>
      ) : null}
    </div>
  );
}
