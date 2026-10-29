"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDownUp, BadgeCheck, Download, ExternalLink, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { DemoBadge, PriorityBadge, ScorePill } from "@/components/badges";
import { Button } from "@/components/ui/button";
import { Badge, Card, Checkbox, Dialog, Field, Input, Select, Table, Td, Th } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { useLeads, useMeta } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api, download } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export const manualLeadSchema = z.object({
  name: z.string().trim().min(1).max(300),
  website_url: z.union([z.literal(""), z.url()]).optional(),
  country: z.union([z.literal(""), z.string().regex(/^[A-Z]{2}$/)]).optional(),
  city: z.string().max(120).optional(),
  industry: z.string().max(120).optional(),
  email: z.union([z.literal(""), z.email()]).optional(),
  phone: z.string().max(40).optional(),
});
type ManualLead = z.infer<typeof manualLeadSchema>;

function AddLeadDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { t, vmsg } = useI18n();
  const qc = useQueryClient();
  const form = useForm<ManualLead>({ resolver: zodResolver(manualLeadSchema), defaultValues: { country: "SA" } });
  const create = useMutation({
    mutationFn: (v: ManualLead) =>
      api("/leads", {
        method: "POST",
        body: Object.fromEntries(Object.entries(v).map(([k, val]) => [k, val === "" ? null : val])),
      }),
    onSuccess: () => {
      toast.success(t.leads.leadAdded);
      qc.invalidateQueries({ queryKey: ["leads"] });
      form.reset();
      onOpenChange(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const err = form.formState.errors;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t.leads.add}
      description={t.leads.manualDesc}
      footer={
        <Button onClick={form.handleSubmit((v) => create.mutate(v))} disabled={create.isPending}>
          {create.isPending ? <Spinner /> : null} {t.common.save}
        </Button>
      }
    >
      <form className="grid gap-3 sm:grid-cols-2" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
        <Field label={t.leads.company} htmlFor="ml-name" error={vmsg(err.name?.message)} className="sm:col-span-2">
          <Input id="ml-name" {...form.register("name")} />
        </Field>
        <Field label={t.leads.website} htmlFor="ml-web" error={vmsg(err.website_url?.message)} className="sm:col-span-2">
          <Input id="ml-web" placeholder="https://" {...form.register("website_url")} />
        </Field>
        <Field label={t.leads.countryIso} htmlFor="ml-country" error={vmsg(err.country?.message)}>
          <Input id="ml-country" maxLength={2} {...form.register("country")} />
        </Field>
        <Field label={t.leads.city} htmlFor="ml-city">
          <Input id="ml-city" {...form.register("city")} />
        </Field>
        <Field label={t.leads.email} htmlFor="ml-email" error={vmsg(err.email?.message)}>
          <Input id="ml-email" type="email" {...form.register("email")} />
        </Field>
        <Field label={t.leads.phone} htmlFor="ml-phone">
          <Input id="ml-phone" {...form.register("phone")} />
        </Field>
      </form>
    </Dialog>
  );
}

export function LeadsTable({ campaignId, compact = false }: { campaignId?: string; compact?: boolean }) {
  const { t, locale, label } = useI18n();
  const meta = useMeta();
  const qc = useQueryClient();
  const [filters, setFilters] = useState({
    q: "",
    country: "",
    industry: "",
    priority: "",
    crm_status: "",
    min_score: "",
    has_contact: "",
    source: "",
    is_demo: "",
  });
  const [sort, setSort] = useState<{ sort: string; order: "asc" | "desc" }>({ sort: "score", order: "desc" });
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);
  const pageSize = compact ? 10 : 25;
  const query = {
    ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== "")),
    campaign_id: campaignId,
    page,
    page_size: pageSize,
    ...sort,
  };
  const { data, isLoading, error, refetch, isFetching } = useLeads(query);

  const bulk = useMutation({
    mutationFn: (body: { action: string; value?: string }) =>
      api("/leads/bulk", { method: "POST", body: { ids: [...selected], ...body } }),
    onSuccess: (r: unknown) => {
      toast.success((r as { message: string }).message);
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["leads"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  function set<K extends keyof typeof filters>(k: K, v: string) {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(1);
  }
  function toggleSort(col: string) {
    setSort((s) => (s.sort === col ? { sort: col, order: s.order === "desc" ? "asc" : "desc" } : { sort: col, order: "desc" }));
  }
  const allOnPage = data?.items.every((x) => selected.has(x.id)) && (data?.items.length ?? 0) > 0;
  const industryName = (k: string | null) => {
    const i = meta.data?.industries.find((x) => x.key === k);
    return i ? (locale === "ar" ? i.ar : i.en) : label(k);
  };

  const serviceName = (k: string | null) => {
    const sv = meta.data?.services.find((x) => x.key === k);
    return sv ? (locale === "ar" ? sv.ar : sv.en) : label(k);
  };

  function exportFiltered(format: "csv" | "xlsx") {
    const q: Record<string, string> = { ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== "")), format };
    if (campaignId) q.campaign_id = campaignId;
    if (selected.size) q.ids = [...selected].join(",");
    download("/exports/leads", q).catch((e) => toast.error(e.message));
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-52 flex-1">
          <Search className="absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" name="q" autoComplete="off" aria-label={t.common.search} placeholder={t.common.search} className="ps-9" value={filters.q} onChange={(e) => set("q", e.target.value)} />
        </div>
        {!compact ? (
          <>
            <Select aria-label={t.campaigns.country} className="w-32" value={filters.country} onChange={(e) => set("country", e.target.value)}>
              <option value="">{t.campaigns.country}</option>
              {meta.data?.countries.map((c) => <option key={c.code} value={c.code}>{locale === "ar" ? c.name_ar : c.code}</option>)}
            </Select>
            <Select aria-label={t.leads.industry} className="w-40" value={filters.industry} onChange={(e) => set("industry", e.target.value)}>
              <option value="">{t.leads.industry}</option>
              {meta.data?.industries.map((i) => <option key={i.key} value={i.key}>{locale === "ar" ? i.ar : i.en}</option>)}
            </Select>
            <Select aria-label={t.leads.crmStatus} className="w-40" value={filters.crm_status} onChange={(e) => set("crm_status", e.target.value)}>
              <option value="">{t.leads.crmStatus}</option>
              {Object.entries(t.crm).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
            <Select aria-label={t.leads.source} className="w-32" value={filters.source} onChange={(e) => set("source", e.target.value)}>
              <option value="">{t.leads.source}</option>
              {["google_maps", "osm", "import", "brave", "hunter", "x", "facebook", "manual", "demo"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
            </Select>
            <Select aria-label={t.leads.data} className="w-32" value={filters.is_demo} onChange={(e) => set("is_demo", e.target.value)}>
              <option value="">{t.leads.realAndDemo}</option>
              <option value="false">{t.leads.realOnly}</option>
              <option value="true">{t.leads.demoOnly}</option>
            </Select>
          </>
        ) : null}
        <Select aria-label={t.leads.priority} className="w-36" value={filters.priority} onChange={(e) => set("priority", e.target.value)}>
          <option value="">{t.leads.priority}</option>
          {Object.entries(t.priority).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
        <Select aria-label={t.leads.contacts} className="w-36" value={filters.has_contact} onChange={(e) => set("has_contact", e.target.value)}>
          <option value="">{t.leads.contacts}</option>
          <option value="true">{t.leads.withContacts}</option>
          <option value="false">{t.common.notFound}</option>
        </Select>
        <Input aria-label={t.leads.minScore} type="number" min={0} max={100} placeholder={t.leads.minScore} className="w-28" value={filters.min_score} onChange={(e) => set("min_score", e.target.value)} />
        {!compact ? (
          <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
            <Plus /> {t.leads.add}
          </Button>
        ) : null}
        <Button variant="outline" size="sm" onClick={() => exportFiltered("csv")}><Download /> CSV</Button>
        <Button variant="outline" size="sm" onClick={() => exportFiltered("xlsx")}><Download /> XLSX</Button>
      </div>

      {selected.size > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-brand-500/40 bg-brand-500/10 p-2 text-xs">
          <span className="font-medium">{selected.size} {t.leads.selected}</span>
          <Select aria-label={t.leads.crmStatus} className="h-8 w-44 text-xs" defaultValue="" onChange={(e) => e.target.value && bulk.mutate({ action: "set_status", value: e.target.value })}>
            <option value="">{t.leads.crmStatus}…</option>
            {Object.entries(t.crm).filter(([k]) => k !== "do_not_contact").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          <Button size="sm" variant="outline" onClick={() => { const tag = window.prompt(t.leads.addTag); if (tag) bulk.mutate({ action: "add_tag", value: tag }); }}>{t.leads.addTag}</Button>
          <Button size="sm" variant="outline" onClick={() => window.confirm(`${t.leads.suppress}?`) && bulk.mutate({ action: "suppress", value: "Bulk suppression" })}>{t.leads.suppress}</Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>{t.common.clear}</Button>
        </div>
      ) : null}

      {isLoading ? (
        <LoadingState rows={compact ? 4 : 8} />
      ) : error ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : !data || data.items.length === 0 ? (
        <EmptyState title={t.common.empty} />
      ) : (
        <Card className={isFetching ? "opacity-80 transition-opacity" : undefined}>
          <Table>
            <thead className="border-b">
              <tr>
                <Th className="w-8">
                  <Checkbox
                    aria-label={t.common.selectAll}
                    checked={allOnPage ?? false}
                    onCheckedChange={(v) =>
                      setSelected((s) => {
                        const n = new Set(s);
                        data.items.forEach((x) => (v ? n.add(x.id) : n.delete(x.id)));
                        return n;
                      })
                    }
                  />
                </Th>
                <Th><button className="inline-flex items-center gap-1" onClick={() => toggleSort("name")}>{t.leads.company}<ArrowDownUp className="size-3" /></button></Th>
                <Th>{t.leads.location}</Th>
                {!compact ? <Th>{t.leads.industry}</Th> : null}
                <Th>{t.leads.contacts}</Th>
                <Th><button className="inline-flex items-center gap-1" onClick={() => toggleSort("score")}>{t.leads.score}<ArrowDownUp className="size-3" /></button></Th>
                <Th>{t.leads.service}</Th>
                {!compact ? <Th>{t.leads.campaign}</Th> : null}
                {!compact ? <Th>{t.leads.source}</Th> : null}
                <Th>{t.leads.crmStatus}</Th>
                {!compact ? <Th><button className="inline-flex items-center gap-1" onClick={() => toggleSort("updated_at")}>{t.leads.updated}<ArrowDownUp className="size-3" /></button></Th> : null}
              </tr>
            </thead>
            <tbody>
              {data.items.map((l) => (
                <tr key={l.id} className="border-b last:border-0 hover:bg-muted/40">
                  <Td>
                    <Checkbox
                      aria-label={`${t.common.select} ${l.name}`}
                      checked={selected.has(l.id)}
                      onCheckedChange={(v) => setSelected((s) => { const n = new Set(s); if (v) n.add(l.id); else n.delete(l.id); return n; })}
                    />
                  </Td>
                  <Td className="max-w-64">
                    <Link href={`/leads/${l.id}`} className="font-medium hover:text-primary hover:underline">{l.name}</Link>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                      {l.website_url ? (
                        <a href={l.website_url} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-0.5 hover:underline">
                          {l.normalized_domain ?? l.website_url}<ExternalLink className="size-3" />
                        </a>
                      ) : null}
                      {l.is_demo ? <DemoBadge /> : null}
                      {l.tags.map((tag) => <Badge key={tag} tone="indigo">{tag}</Badge>)}
                    </div>
                  </Td>
                  <Td className="whitespace-nowrap text-xs">{[l.country, l.city].filter(Boolean).join(" · ") || "—"}</Td>
                  {!compact ? <Td className="text-xs">{industryName(l.industry)}</Td> : null}
                  <Td className="text-xs">
                    {l.contact_count ? (
                      <span className="inline-flex items-center gap-1">
                        {l.contact_count}
                        {l.has_verified_contact ? <BadgeCheck className="size-3.5 text-success" aria-label={t.verification.verified} /> : null}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">{t.common.notFound}</span>
                    )}
                  </Td>
                  <Td>
                    <div className="flex items-center gap-1.5">
                      <ScorePill score={l.latest_score} />
                      <PriorityBadge priority={l.latest_priority} />
                    </div>
                  </Td>
                  <Td className="text-xs">{serviceName(l.recommended_service)}</Td>
                  {!compact ? <Td className="max-w-40 truncate text-xs">{l.campaigns.map((c) => c.name).join(", ") || "—"}</Td> : null}
                  {!compact ? <Td className="text-xs">{l.sources.map((s) => label(s)).join(locale === "ar" ? "، " : ", ")}</Td> : null}
                  <Td>
                    <Badge tone={l.crm_status === "do_not_contact" ? "red" : l.crm_status === "new" ? "neutral" : "blue"}>
                      {t.crm[l.crm_status as keyof typeof t.crm] ?? l.crm_status}
                    </Badge>
                  </Td>
                  {!compact ? <Td className="whitespace-nowrap text-xs text-muted-foreground">{formatDate(l.updated_at, locale)}</Td> : null}
                </tr>
              ))}
            </tbody>
          </Table>
          <div className="flex items-center justify-between border-t p-3 text-xs text-muted-foreground">
            <span>
              {t.common.page} {page} {t.common.of} {Math.max(1, Math.ceil(data.total / pageSize))} · {t.common.total} {data.total}
            </span>
            <div className="flex gap-1">
              <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t.common.back}</Button>
              <Button size="sm" variant="outline" disabled={page * pageSize >= data.total} onClick={() => setPage(page + 1)}>{t.common.next}</Button>
            </div>
          </div>
        </Card>
      )}
      <AddLeadDialog open={adding} onOpenChange={setAdding} />
    </div>
  );
}
