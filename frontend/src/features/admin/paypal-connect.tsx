"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, Link2, Unplug } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Dialog, Field, Input, Select } from "@/components/ui/primitives";
import { ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";

interface PayPalStatus {
  connected: boolean;
  mode: "live" | "sandbox" | null;
  client_id: string | null;
  webhook: boolean;
  webhook_url: string;
}

const DEV_APPS = "https://developer.paypal.com/dashboard/applications/live";

/** The store's PayPal account (backend services/paypal.py). Clients pay for packages through it. */
export function PayPalConnect() {
  const { t } = useI18n();
  const pp = t.admin.paypal;
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin-paypal"], queryFn: () => api<PayPalStatus>("/admin/paypal") });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ client_id: "", client_secret: "", mode: "live" });
  const done = (s: PayPalStatus) => {
    qc.setQueryData(["admin-paypal"], s);
    qc.invalidateQueries({ queryKey: ["billing-summary"] });
  };
  const connect = useMutation({
    mutationFn: () => api<PayPalStatus>("/admin/paypal", { method: "PUT", body: form }),
    onSuccess: (s) => {
      done(s);
      setOpen(false);
      setForm({ client_id: "", client_secret: "", mode: "live" });
      toast.success(pp.connected);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const disconnect = useMutation({
    mutationFn: () => api<PayPalStatus>("/admin/paypal", { method: "DELETE" }),
    onSuccess: done,
    onError: (e: Error) => toast.error(e.message),
  });

  if (q.isLoading) return <LoadingState rows={2} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const s = q.data;
  const valid = form.client_id.trim().length >= 10 && form.client_secret.trim().length >= 10;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          PayPal
          {s.connected ? (
            <Badge tone="green"><CheckCircle2 className="size-3" /> {pp.connected}{s.mode === "sandbox" ? ` · ${pp.sandbox}` : ""}</Badge>
          ) : (
            <Badge tone="neutral">{pp.notConnected}</Badge>
          )}
        </CardTitle>
        <CardDescription>{pp.hint}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {s.connected ? (
          <>
            <p className="text-xs text-muted-foreground" dir="ltr">Client ID: {s.client_id}</p>
            <p className="text-xs text-muted-foreground">{s.webhook ? pp.webhookOn : pp.webhookOff}</p>
          </>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setOpen(true)}>
            <Link2 /> {s.connected ? pp.reconnect : pp.connect}
          </Button>
          {s.connected ? (
            <Button variant="outline" disabled={disconnect.isPending} onClick={() => confirm(pp.disconnectConfirm) && disconnect.mutate()}>
              {disconnect.isPending ? <Spinner /> : <Unplug />} {pp.disconnect}
            </Button>
          ) : null}
        </div>
      </CardContent>

      <Dialog
        open={open}
        onOpenChange={setOpen}
        title={pp.connect}
        description={pp.dialogHint}
        footer={
          <Button disabled={!valid || connect.isPending} onClick={() => connect.mutate()}>
            {connect.isPending ? <Spinner /> : <Link2 />} {pp.connect}
          </Button>
        }
      >
        <div className="space-y-4">
          <ol className="list-decimal space-y-1 ps-5 text-sm">
            <li>
              <a href={DEV_APPS} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary underline">
                {pp.step1} <ExternalLink className="size-3" />
              </a>
            </li>
            <li>{pp.step2}</li>
            <li>{pp.step3}</li>
          </ol>
          <Field label="Client ID" htmlFor="pp_id">
            <Input id="pp_id" dir="ltr" autoComplete="off" value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} />
          </Field>
          <Field label="Secret" htmlFor="pp_secret">
            <Input id="pp_secret" dir="ltr" type="password" autoComplete="off" value={form.client_secret} onChange={(e) => setForm({ ...form, client_secret: e.target.value })} />
          </Field>
          <Field label={pp.mode} htmlFor="pp_mode">
            <Select id="pp_mode" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
              <option value="live">{pp.live}</option>
              <option value="sandbox">{pp.sandbox}</option>
            </Select>
          </Field>
        </div>
      </Dialog>
    </Card>
  );
}
