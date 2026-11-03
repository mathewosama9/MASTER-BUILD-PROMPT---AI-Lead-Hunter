"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { toast } from "sonner";

import { Card, CardContent, Switch, Table, Td, Th } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import type { NotificationPrefs, NotifyChannel } from "@/types/api";

const CHANNELS: NotifyChannel[] = ["in_app", "email", "telegram"];
const CATEGORY_ORDER = ["campaigns", "billing", "account", "news", "admin"];

/** Settings → Notifications: per kind and channel, within what the platform admin allows. */
export function NotificationPrefsTab({ onLinkTelegram }: { onLinkTelegram: () => void }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["notification-prefs"],
    queryFn: () => api<NotificationPrefs>("/notifications/preferences"),
  });
  const save = useMutation({
    mutationFn: (body: { key: string; channel: NotifyChannel; on: boolean }) =>
      api<NotificationPrefs>("/notifications/preferences", {
        method: "PUT",
        body: { prefs: { [body.key]: { [body.channel]: body.on } } },
      }),
    onSuccess: (prefs) => qc.setQueryData(["notification-prefs"], prefs),
    onError: (e: Error) => toast.error(e.message),
  });
  if (isLoading) return <LoadingState />;
  if (error || !data) return <ErrorState error={error} />;

  const groups = CATEGORY_ORDER.map((c) => ({ category: c, kinds: data.kinds.filter((k) => k.category === c) })).filter((g) => g.kinds.length);
  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <div>
          <p className="text-sm font-semibold">{t.notify.prefsTitle}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t.notify.prefsHint}</p>
        </div>
        {!data.telegram_linked ? (
          <p className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-xs text-muted-foreground">
            {t.notify.telegramOff}
            <button type="button" onClick={onLinkTelegram} className="font-medium text-foreground underline-offset-2 hover:underline">
              {t.notify.linkTelegram}
            </button>
          </p>
        ) : null}
        {!data.email_verified ? <p className="rounded-lg border border-dashed px-3 py-2 text-xs text-muted-foreground">{t.notify.emailUnverified}</p> : null}
        <div className="-mx-6">
          <Table>
            <thead className="border-b">
              <tr>
                <Th className="ps-6">{t.notify.admin.kind}</Th>
                {CHANNELS.map((c) => (
                  <Th key={c} className="w-24 text-center">
                    {t.notify.channels[c]}
                  </Th>
                ))}
              </tr>
            </thead>
            {groups.map((g) => (
              <tbody key={g.category} className="border-b last:border-0">
                <tr>
                  <td colSpan={4} className="bg-muted/40 px-6 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {t.notify.categories[g.category]}
                  </td>
                </tr>
                {g.kinds.map((k) => (
                  <tr key={k.key} className="border-t first:border-0">
                    <Td className="ps-6 text-sm">
                      {t.notify.kinds[k.key] ?? k.key}
                      {k.locked ? (
                        <span className="ms-2 inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                          <Lock className="size-3" aria-hidden /> {t.notify.locked}
                        </span>
                      ) : null}
                    </Td>
                    {CHANNELS.map((c) => {
                      const ch = k.channels[c];
                      const unreachable = c === "telegram" && !data.telegram_linked;
                      const name = `${t.notify.kinds[k.key] ?? k.key}: ${t.notify.channels[c]}`;
                      return (
                        <Td key={c} className="text-center">
                          {ch.allowed ? (
                            <span className="inline-flex" title={unreachable ? t.notify.telegramOff : undefined}>
                              <Switch
                                aria-label={name}
                                checked={ch.on && !unreachable}
                                disabled={k.locked || unreachable || save.isPending}
                                onCheckedChange={(on) => save.mutate({ key: k.key, channel: c, on })}
                              />
                            </span>
                          ) : (
                            <span className="text-xs text-muted-foreground" title={t.notify.notOffered} aria-label={`${name}: ${t.notify.notOffered}`}>
                              —
                            </span>
                          )}
                        </Td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            ))}
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}
