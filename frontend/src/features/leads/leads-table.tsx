"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDownUp, BadgeCheck, Ban, ChevronRight, Download, ExternalLink, Phone, Plus, Search, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { DemoBadge, PriorityBadge, ScorePill } from "@/components/badges";
import { Button } from "@/components/ui/button";
import { Badge, Card, Checkbox, Dialog, Field, Input, Select, Table, Td, Th } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { useLeads, useMeta, useServiceName } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api, download } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";

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
  const form = useForm<ManualLead>({ resolver: zodResolver(manualLeadSchema), defaultValues: { country: "EG" } });
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

export function LeadsTable({
  campaignId,
  crmStatus = "",
  compact = false,
}: {
  campaignId?: string;
  crmStatus?: string;
  compact?: boolean;
}) {
  const { t, locale, label, source } = useI18n();
  const meta = useMeta();
  const qc = useQueryClient();
  const [filters, setFilters] = useState({
    q: "",
    country: "",
    industry: "",
    priority: "",
    crm_status: crmStatus,
    min_score: "",
    has_contact: "",
    source: "",
    is_demo: "false", // real leads only; demo data is never listed
  });
  const [sort, setSort] = useState<{ sort: string; order: "asc" | "desc" }>({ sort: "score", order: "desc" });
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [tagging, setTagging] = useState(false);
  const [tagValue, setTagValue] = useState("");
  const [suppressing, setSuppressing] = useState(false);
  const pageSize = compact ? 10 : 25;
  const query = {
    ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== "")),
    campaign_id: campaignId,
    page,
    page_size: pageSize,
    ...sort,
  };
  const { data, isLoading, error, refetch, isFetching } = useLeads(query);
  const activeFilters = Object.entries(filters).filter(([k, v]) => k !== "q" && v !== "").length;

  const bulk = useMutation({
    mutationFn: (body: { action: string; value?: string }) =>
      api("/leads/bulk", { method: "POST", body: { ids: [...selected], ...body } }),
    onSuccess: (r: unknown) => {
      toast.success((r as { message: string }).message);
      setSelected(new Set());
      setTagging(false);
      setTagValue("");
      setSuppressing(false);
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
  const ariaSort = (col: string) => (sort.sort === col ? (sort.order === "asc" ? "ascending" : "descending") : "none");
  const allOnPage = data?.items.every((x) => selected.has(x.id)) && (data?.items.length ?? 0) > 0;
  const industryName = (k: string | null) => {
    const i = meta.data?.industries.find((x) => x.key === k);
    return i ? (locale === "ar" ? i.ar : i.en) : label(k);
  };

  const nameOf = useServiceName();
  const serviceName = (k: string | null) => (k ? nameOf(k, locale) : label(k));
  const crmBadge = (status: string) => (
    <Badge tone={status === "do_not_contact" ? "red" : status === "new" ? "neutral" : "blue"}>
      {t.crm[status as keyof typeof t.crm] ?? status}
    </Badge>
  );

  function exportFiltered(format: "csv" | "xlsx") {
    const q: Record<string, string> = { ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== "")), format };
    if (campaignId) q.campaign_id = campaignId;
    if (selected.size) q.ids = [...selected].join(",");
    download("/exports/leads", q).catch((e) => toast.error(e.message));
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 md:min-w-52">
          <Search className="absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" name="q" autoComplete="off" aria-label={t.common.search} placeholder={t.common.search} className="ps-9" value={filters.q} onChange={(e) => set("q", e.target.value)} />
        </div>
        {/* Phones get the filters behind one button; from md up they sit inline (display: contents). */}
        <Button variant="outline" className="md:hidden" onClick={() => setShowFilters((v) => !v)} aria-expanded={showFilters} aria-controls="lead-filters">
          <SlidersHorizontal /> {t.common.filters}
          {activeFilters ? <span className="rounded-full bg-signal-400 px-1.5 text-xs font-semibold text-ink-900">{activeFilters}</span> : null}
        </Button>
        <div id="lead-filters" className={cn("w-full grid-cols-2 gap-2 md:contents", showFilters ? "grid" : "hidden")}>
          {!compact ? (
            <>
              <Select aria-label={t.campaigns.country} className="w-full md:w-32" value={filters.country} onChange={(e) => set("country", e.target.value)}>
                <option value="">{t.campaigns.country}</option>
                {meta.data?.countries.map((c) => <option key={c.code} value={c.code}>{locale === "ar" ? c.name_ar : c.code}</option>)}
              </Select>
              <Select aria-label={t.leads.industry} className="w-full md:w-40" value={filters.industry} onChange={(e) => set("industry", e.target.value)}>
                <option value="">{t.leads.industry}</option>
                {meta.data?.industries.map((i) => <option key={i.key} value={i.key}>{locale === "ar" ? i.ar : i.en}</option>)}
              </Select>
              <Select aria-label={t.leads.crmStatus} className="w-full md:w-40" value={filters.crm_status} onChange={(e) => set("crm_status", e.target.value)}>
                <option value="">{t.leads.crmStatus}</option>
                {Object.entries(t.crm).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>
              <Select aria-label={t.leads.source} className="w-full md:w-32" value={filters.source} onChange={(e) => set("source", e.target.value)}>
                <option value="">{t.leads.source}</option>
                {["google_maps", "osm", "directories", "social_discovery", "import", "brave", "hunter", "x", "facebook", "manual"].map((s) => <option key={s} value={s}>{t.customerSources[s]?.name ?? source(s)}</option>)}
              </Select>
            </>
          ) : null}
          <Select aria-label={t.leads.priority} className="w-full md:w-36" value={filters.priority} onChange={(e) => set("priority", e.target.value)}>
            <option value="">{t.leads.priority}</option>
            {Object.entries(t.priority).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          <Select aria-label={t.leads.contacts} className="w-full md:w-36" value={filters.has_contact} onChange={(e) => set("has_contact", e.target.value)}>
            <option value="">{t.leads.contacts}</option>
            <option value="true">{t.leads.withContacts}</option>
            <option value="false">{t.common.notFound}</option>
          </Select>
          <Input aria-label={t.leads.minScore} type="number" min={0} max={100} placeholder={t.leads.minScore} className="w-full md:w-28" value={filters.min_score} onChange={(e) => set("min_score", e.target.value)} />
          {!compact ? (
            <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
              <Plus /> {t.leads.add}
            </Button>
          ) : null}
          <Button variant="outline" size="sm" onClick={() => exportFiltered("csv")}><Download /> CSV</Button>
          <Button variant="outline" size="sm" onClick={() => exportFiltered("xlsx")}><Download /> XLSX</Button>
        </div>
      </div>

      {selected.size > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-rasd-500/40 bg-rasd-500/10 p-2 text-xs">
          <span className="font-medium">{selected.size} {t.leads.selected}</span>
          <Select aria-label={t.leads.crmStatus} className="h-8 w-44 text-xs" defaultValue="" onChange={(e) => e.target.value && bulk.mutate({ action: "set_status", value: e.target.value })}>
            <option value="">{t.leads.crmStatus}…</option>
            {Object.entries(t.crm).filter(([k]) => k !== "do_not_contact").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          <Button size="sm" variant="outline" onClick={() => setTagging(true)}>{t.leads.addTag}</Button>
          <Button size="sm" variant="outline" onClick={() => setSuppressing(true)}>{t.leads.suppress}</Button>
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
          {/* Phones: one tappable card per lead; the 11-column table only from md up. */}
          <ul className="divide-y md:hidden">
            {data.items.map((l) => (
              <li key={l.id}>
                <Link href={`/app/leads/${l.id}`} className="flex items-start gap-3 p-4 transition-colors active:bg-muted">
                  <ScorePill score={l.latest_score} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{l.name}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {[l.industry ? industryName(l.industry) : null, l.city, l.country].filter(Boolean).join(" · ") || "—"}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <PriorityBadge priority={l.latest_priority} />
                      {crmBadge(l.crm_status)}
                      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                        <Phone className="size-3.5" aria-hidden />
                        {l.contact_count ? l.contact_count : t.common.notFound}
                        {l.has_verified_contact ? <BadgeCheck className="size-3.5 text-success" aria-label={t.verification.verified} /> : null}
                      </span>
                      {l.is_demo ? <DemoBadge /> : null}
                    </div>
                  </div>
                  <ChevronRight className="mt-1 size-4 shrink-0 text-muted-foreground rtl:rotate-180" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
          <div className="hidden md:block">
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
                  <Th aria-sort={ariaSort("name")}><button className="inline-flex items-center gap-1" onClick={() => toggleSort("name")}>{t.leads.company}<ArrowDownUp className="size-3" aria-hidden /></button></Th>
                  <Th>{t.leads.location}</Th>
                  {!compact ? <Th>{t.leads.industry}</Th> : null}
                  <Th>{t.leads.contacts}</Th>
                  <Th aria-sort={ariaSort("score")}><button className="inline-flex items-center gap-1" onClick={() => toggleSort("score")}>{t.leads.score}<ArrowDownUp className="size-3" aria-hidden /></button></Th>
                  <Th>{t.leads.service}</Th>
                  {!compact ? <Th>{t.leads.campaign}</Th> : null}
                  {!compact ? <Th>{t.leads.source}</Th> : null}
                  <Th>{t.leads.crmStatus}</Th>
                  {!compact ? <Th aria-sort={ariaSort("updated_at")}><button className="inline-flex items-center gap-1" onClick={() => toggleSort("updated_at")}>{t.leads.updated}<ArrowDownUp className="size-3" aria-hidden /></button></Th> : null}
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
                      <Link href={`/app/leads/${l.id}`} className="font-medium hover:text-primary hover:underline">{l.name}</Link>
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
                    {!compact ? <Td className="text-xs">{[...new Set(l.sources.map((s) => source(s)))].join(locale === "ar" ? "، " : ", ")}</Td> : null}
                    <Td>{crmBadge(l.crm_status)}</Td>
                    {!compact ? <Td className="whitespace-nowrap text-xs text-muted-foreground">{formatDate(l.updated_at, locale)}</Td> : null}
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
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
      <Dialog
        open={tagging}
        onOpenChange={setTagging}
        title={t.leads.addTag}
        footer={
          <Button disabled={!tagValue.trim() || bulk.isPending} onClick={() => bulk.mutate({ action: "add_tag", value: tagValue.trim() })}>
            {bulk.isPending ? <Spinner /> : null} {t.common.save}
          </Button>
        }
      >
        <form onSubmit={(e) => { e.preventDefault(); if (tagValue.trim()) bulk.mutate({ action: "add_tag", value: tagValue.trim() }); }}>
          <Field label={t.leads.tagLabel} htmlFor="bulk-tag">
            <Input id="bulk-tag" autoFocus maxLength={60} value={tagValue} onChange={(e) => setTagValue(e.target.value)} />
          </Field>
        </form>
      </Dialog>
      <Dialog
        open={suppressing}
        onOpenChange={setSuppressing}
        title={t.leads.suppressSelected.replace("{n}", String(selected.size))}
        description={t.leads.suppressConfirm}
        footer={
          <>
            <Button variant="ghost" onClick={() => setSuppressing(false)}>{t.common.cancel}</Button>
            <Button variant="destructive" disabled={bulk.isPending} onClick={() => bulk.mutate({ action: "suppress", value: "Bulk suppression" })}>
              {bulk.isPending ? <Spinner /> : <Ban />} {t.leads.suppress}
            </Button>
          </>
        }
      >
        {null}
      </Dialog>
    </div>
  );
}
