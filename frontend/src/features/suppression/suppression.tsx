"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, Input, Select, Table, Td, Th } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";

interface Entry {
  id: string;
  kind: string;
  value: string;
  reason: string | null;
  created_at: string;
}

export function SuppressionPage() {
  const { t, locale, label } = useI18n();
  const qc = useQueryClient();
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["suppression"], queryFn: () => api<Entry[]>("/suppression") });
  const [form, setForm] = useState({ kind: "domain", value: "", reason: "" });
  const add = useMutation({
    mutationFn: () => api("/suppression", { method: "POST", body: form }),
    onSuccess: () => { setForm({ ...form, value: "", reason: "" }); qc.invalidateQueries({ queryKey: ["suppression"] }); toast.success(t.common.added); },
    onError: (e: Error) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/suppression/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["suppression"] }),
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <div>
      <PageHeader title={t.suppression.title} subtitle={t.suppression.subtitle} />
      <Card className="mb-4">
        <CardContent className="flex flex-wrap gap-2 p-4">
          <Select aria-label={t.suppression.kind} className="w-36" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            <option value="domain">{label("domain")}</option>
            <option value="email">{label("email")}</option>
            <option value="phone">{label("phone")}</option>
          </Select>
          <Input aria-label={t.suppression.value} className="min-w-56 flex-1" placeholder={form.kind === "phone" ? "+9665..." : form.kind === "email" ? "name@company.com" : "company.com"} value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
          <Input aria-label={t.suppression.reason} className="min-w-48 flex-1" placeholder={t.suppression.reason} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          <Button onClick={() => add.mutate()} disabled={!form.value || add.isPending}>{t.suppression.add}</Button>
        </CardContent>
      </Card>
      {isLoading ? <LoadingState /> : error ? <ErrorState error={error} onRetry={() => refetch()} /> : !data?.length ? <EmptyState title={t.common.empty} /> : (
        <Card>
          <Table>
            <thead className="border-b"><tr><Th>{t.suppression.kind}</Th><Th>{t.suppression.value}</Th><Th>{t.suppression.reason}</Th><Th>{t.campaigns.created}</Th><Th /></tr></thead>
            <tbody>
              {data.map((e) => (
                <tr key={e.id} className="border-b last:border-0">
                  <Td><Badge tone="red">{label(e.kind)}</Badge></Td>
                  <Td className="font-mono text-xs" dir="ltr">{e.value}</Td>
                  <Td className="text-xs">{e.reason ?? "—"}</Td>
                  <Td className="text-xs text-muted-foreground">{formatDate(e.created_at, locale)}</Td>
                  <Td className="text-end"><Button size="icon" variant="ghost" aria-label={t.common.delete} onClick={() => window.confirm(`${t.common.delete}?`) && remove.mutate(e.id)}><Trash2 /></Button></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </div>
  );
}
