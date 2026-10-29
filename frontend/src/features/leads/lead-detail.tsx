"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  CheckCircle2,
  CircleHelp,
  Copy,
  ExternalLink,
  FileText,
  Globe,
  Lightbulb,
  Mail,
  MessageCircle,
  Phone,
  RefreshCw,
  Share2,
  ShieldAlert,
  User,
  X,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { DemoBadge, PriorityBadge, ScorePill, VerificationBadge } from "@/components/badges";
import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input, Select, Tabs, TabsContent, TabsList, TabsTrigger, Textarea } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { useLead, useMeta } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/utils";
import type { Contact, Draft, LeadDetail } from "@/types/api";

const CONTACT_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  email: Mail,
  phone: Phone,
  whatsapp: MessageCircle,
  social: Share2,
  contact_page: Globe,
  person: User,
};

function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>{title}</CardTitle>
        {action}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function CopyButton({ text }: { text: string }) {
  const { t } = useI18n();
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => navigator.clipboard.writeText(text).then(() => toast.success(t.common.copied))}
    >
      <Copy /> {t.common.copy}
    </Button>
  );
}

function ContactRow({ c, leadId }: { c: Contact; leadId: string }) {
  const { t, locale, label } = useI18n();
  const qc = useQueryClient();
  const Icon = CONTACT_ICON[c.type] ?? Globe;
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => api(`/contacts/${c.id}`, { method: "PATCH", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lead", leadId] }),
    onError: (e: Error) => toast.error(e.message),
  });
  const href = c.type === "email" ? `mailto:${c.value}` : c.type === "phone" ? `tel:${c.value}` : c.type === "whatsapp" ? `https://wa.me/${c.value.replace(/\D/g, "")}` : c.value;
  return (
    <li className={`flex items-start gap-3 rounded-md border p-3 ${c.is_suppressed ? "opacity-60" : ""}`}>
      <Icon className="mt-0.5 size-4 text-primary" />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <a href={href} target={c.type === "email" || c.type === "phone" ? undefined : "_blank"} rel="noopener noreferrer nofollow" className={`break-all text-sm font-medium hover:underline ${c.is_suppressed ? "line-through" : ""}`}>
            {c.value}
          </a>
          <Badge tone="neutral">{label(c.type)}{c.subtype ? ` · ${label(c.subtype)}` : ""}</Badge>
          <VerificationBadge status={c.verification_status} />
          {c.is_suppressed ? <Badge tone="red">{t.leads.suppressed}</Badge> : null}
        </div>
        {c.person_name ? <p className="text-xs">{c.person_name}{c.person_role ? ` — ${c.person_role}` : ""}</p> : null}
        <p className="text-[11px] text-muted-foreground">
          {label(c.source_provider)} · {t.leads.confidence} {Math.round(c.confidence * 100)}% · {t.leads.retrieved} {formatDate(c.retrieved_at, locale)}
          {c.source_url ? (
            <> · <a href={c.source_url} target="_blank" rel="noopener noreferrer nofollow" className="hover:underline">{t.leads.sourceLink}</a></>
          ) : null}
        </p>
        {c.usage_restrictions ? (
          <p className="flex items-start gap-1 text-[11px] text-warning">
            <ShieldAlert className="mt-px size-3 shrink-0" /> {t.restrictions[c.usage_restrictions] ?? c.usage_restrictions}
          </p>
        ) : null}
        <div className="flex gap-1 pt-1">
          {c.verification_status !== "invalid" ? (
            <Button size="sm" variant="outline" className="h-7" onClick={() => update.mutate({ verification_status: "invalid" })}>{t.leads.markInvalid}</Button>
          ) : null}
          <Button size="sm" variant="outline" className="h-7" onClick={() => update.mutate({ is_suppressed: !c.is_suppressed })}>
            {c.is_suppressed ? t.leads.unsuppress : t.leads.suppressAction}
          </Button>
        </div>
      </div>
    </li>
  );
}

function DraftView({ d }: { d: Draft }) {
  const { t, locale, label } = useI18n();
  const blocks: [string, string][] = [
    [t.leads.shortIntro, d.short_intro],
    [`${t.leads.emailDraft} — ${d.email_subject}`, d.email_body],
    [t.leads.whatsapp, d.whatsapp_message],
    [t.leads.followUp, d.follow_up],
    [t.leads.proposal, d.proposal_summary],
  ];
  return (
    <div className="space-y-3" dir={d.language === "ar" ? "rtl" : "ltr"}>
      <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
        <Badge tone="indigo">{label(d.provider)}</Badge>
        <span>{d.language.toUpperCase()} · {label(d.tone)} · {label(d.length)} · {label(d.service)} · {formatDate(d.created_at, locale)}</span>
      </div>
      {blocks.map(([label, text]) => (
        <div key={label} className="rounded-md border bg-muted/40 p-3">
          <div className="mb-1 flex items-center justify-between">
            <p className="text-xs font-medium">{label}</p>
            <CopyButton text={text} />
          </div>
          <p className="whitespace-pre-wrap text-sm">{text}</p>
        </div>
      ))}
    </div>
  );
}

function PitchSection({ lead }: { lead: LeadDetail }) {
  const { t, locale, label } = useI18n();
  const meta = useMeta();
  const qc = useQueryClient();
  const [opts, setOpts] = useState({ language: locale as string, tone: "professional", length: "short", service: "" });
  const gen = useMutation({
    mutationFn: () => api<Draft>(`/leads/${lead.business.id}/pitch`, { method: "POST", body: { ...opts, service: opts.service || null } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lead", lead.business.id] }),
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Section title={t.leads.pitch}>
      <p className="mb-3 text-xs text-muted-foreground">{t.leads.draftsNote}</p>
      {lead.suppressed ? (
        <p className="flex items-center gap-2 rounded-md bg-destructive/10 p-3 text-xs text-destructive"><Ban className="size-4" /> {t.leads.suppressed}</p>
      ) : (
        <div className="mb-4 flex flex-wrap gap-2">
          <Select aria-label={t.leads.draftLanguage} className="w-28" value={opts.language} onChange={(e) => setOpts({ ...opts, language: e.target.value })}>
            <option value="en">English</option>
            <option value="ar">العربية</option>
          </Select>
          <Select aria-label={t.leads.tone} className="w-36" value={opts.tone} onChange={(e) => setOpts({ ...opts, tone: e.target.value })}>
            {["professional", "friendly", "concise", "consultative"].map((x) => <option key={x} value={x}>{label(x)}</option>)}
          </Select>
          <Select aria-label={t.leads.length} className="w-28" value={opts.length} onChange={(e) => setOpts({ ...opts, length: e.target.value })}>
            {["short", "medium", "long"].map((x) => <option key={x} value={x}>{label(x)}</option>)}
          </Select>
          <Select aria-label={t.leads.service} className="w-56" value={opts.service} onChange={(e) => setOpts({ ...opts, service: e.target.value })}>
            <option value="">{t.leads.recommendedService}</option>
            {meta.data?.services.map((s) => <option key={s.key} value={s.key}>{locale === "ar" ? s.ar : s.en}</option>)}
          </Select>
          <Button onClick={() => gen.mutate()} disabled={gen.isPending}>
            {gen.isPending ? <Spinner /> : <FileText />} {t.leads.generatePitch}
          </Button>
        </div>
      )}
      {lead.drafts.length ? <DraftView d={lead.drafts[0]} /> : <EmptyState title={t.common.empty} />}
    </Section>
  );
}

export function LeadDetailView({ id }: { id: string }) {
  const { t, locale, label } = useI18n();
  const meta = useMeta();
  const qc = useQueryClient();
  const { data: lead, isLoading, error, refetch } = useLead(id);
  const [note, setNote] = useState("");
  const [tag, setTag] = useState("");
  const invalidate = () => qc.invalidateQueries({ queryKey: ["lead", id] });
  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api(`/leads/${id}`, { method: "PATCH", body }),
    onSuccess: () => { invalidate(); qc.invalidateQueries({ queryKey: ["leads"] }); toast.success(t.common.saved); },
    onError: (e: Error) => toast.error(e.message),
  });
  const addNote = useMutation({
    mutationFn: () => api(`/leads/${id}/notes`, { method: "POST", body: { body: note } }),
    onSuccess: () => { setNote(""); invalidate(); },
    onError: (e: Error) => toast.error(e.message),
  });
  const addTag = useMutation({
    mutationFn: (value: string) => api(`/leads/${id}/tags`, { method: "POST", body: { tag: value } }),
    onSuccess: () => { setTag(""); invalidate(); },
  });
  const removeTag = useMutation({
    mutationFn: (value: string) => api(`/leads/${id}/tags/${encodeURIComponent(value)}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
  const reanalyze = useMutation({
    mutationFn: () => api(`/leads/${id}/reanalyze`, { method: "POST" }),
    onSuccess: () => { invalidate(); toast.success(t.leads.reanalysed); },
    onError: (e: Error) => toast.error(e.message),
  });

  const industryName = (k: string | null) => {
    const i = meta.data?.industries.find((x) => x.key === k);
    return i ? (locale === "ar" ? i.ar : i.en) : label(k);
  };
  const serviceName = (k: string) => {
    const sv = meta.data?.services.find((x) => x.key === k);
    return sv ? (locale === "ar" ? sv.ar : sv.en) : label(k);
  };

  if (isLoading) return <LoadingState rows={8} />;
  if (error || !lead) return <ErrorState error={error} onRetry={() => refetch()} />;
  const b = lead.business;
  const a = lead.assessment;
  const evidenceById = Object.fromEntries((a?.evidence_links ?? []).map((e) => [e.id, e]));
  const signals = lead.evidence.filter((e) => e.kind === "signal");
  const pages = lead.evidence.filter((e) => e.kind === "page");
  // Map listings, public social profiles and schema.org data: observed outside the website's own pages.
  const presence = lead.evidence.filter((e) => ["listing", "social_profile", "structured"].includes(e.kind));
  const fromOsm = presence.some((e) => e.signal_key === "listing:osm");
  const directContacts = lead.contacts.filter((c) => ["email", "phone", "whatsapp", "person"].includes(c.type));
  const otherContacts = lead.contacts.filter((c) => !["email", "phone", "whatsapp", "person"].includes(c.type));

  return (
    <div className="space-y-6">
      <PageHeader
        title={b.name}
        subtitle={[industryName(b.industry), b.city, b.country].filter(Boolean).join(" · ")}
        actions={
          <>
            <Select aria-label={t.leads.crmStatus} className="w-48" value={b.crm_status}
                    onChange={(e) => patch.mutate({ crm_status: e.target.value })}>
              {Object.entries(t.crm).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
            {!lead.suppressed ? (
              <Button variant="destructive" size="sm" onClick={() => window.confirm(`${t.leads.suppress}?`) && patch.mutate({ crm_status: "do_not_contact" })}>
                <Ban /> {t.leads.suppress}
              </Button>
            ) : null}
            <Button variant="outline" size="sm" onClick={() => reanalyze.mutate()} disabled={reanalyze.isPending}>
              {reanalyze.isPending ? <Spinner /> : <RefreshCw />} {t.leads.reanalyse}
            </Button>
          </>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <ScorePill score={b.latest_score} />
        <PriorityBadge priority={b.latest_priority} />
        {b.is_demo ? <DemoBadge /> : null}
        <Badge tone={lead.outreach_eligible ? "green" : "red"}>
          {lead.outreach_eligible ? <CheckCircle2 className="size-3" /> : <Ban className="size-3" />}
          {t.leads.eligible}: {lead.outreach_eligible ? t.common.yes : t.common.no}
        </Badge>
        {lead.tags.map((tg) => (
          <Badge key={tg} tone="indigo">
            {tg}
            <button aria-label={`${t.common.remove} ${tg}`} onClick={() => removeTag.mutate(tg)}><X className="size-3" /></button>
          </Badge>
        ))}
        <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); if (tag.trim()) addTag.mutate(tag.trim()); }}>
          <Input aria-label={t.leads.addTag} placeholder={t.leads.addTag} className="h-7 w-28 text-xs" value={tag} onChange={(e) => setTag(e.target.value)} />
        </form>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Section title={t.leads.overview}>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div><dt className="text-xs text-muted-foreground">{t.leads.website}</dt><dd>{b.website_url ? <a className="inline-flex items-center gap-1 text-primary hover:underline" href={b.website_url} target="_blank" rel="noopener noreferrer nofollow">{b.website_url}<ExternalLink className="size-3" /></a> : t.common.notFound}</dd></div>
              <div><dt className="text-xs text-muted-foreground">{t.leads.location}</dt><dd>{[b.country, b.city, b.address].filter(Boolean).join(" · ") || "—"}</dd></div>
              <div className="sm:col-span-2"><dt className="text-xs text-muted-foreground">{t.leads.description}</dt><dd className="whitespace-pre-wrap">{b.description || t.common.notFound}</dd></div>
            </dl>
          </Section>

          <Section title={t.leads.analysis} action={a ? <Badge tone={a.provider === "heuristic" || a.provider === "demo" ? "yellow" : "indigo"}>{label(a.provider)}{a.model ? ` · ${a.model}` : ""} · {formatMoney(a.cost_usd)}</Badge> : null}>
            {!a ? (
              <EmptyState title={t.leads.notAnalysed} />
            ) : (
              <div className="space-y-5">
                {!["anthropic", "openai", "deepseek"].includes(a.provider) ? (
                  <p className="rounded-md bg-sun-500/10 p-2 text-xs">{t.leads.ruleBased.replace("{p}", label(a.provider))}</p>
                ) : null}
                <p className="text-sm">{a.summary}</p>
                <div>
                  <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold"><CheckCircle2 className="size-3.5 text-success" /> {t.leads.observed}</p>
                  <ul className="space-y-1.5 text-sm">
                    {a.observed_signals.map((s, i) => (
                      <li key={i} className="flex flex-wrap items-baseline gap-2">
                        <span>{s.signal}</span>
                        {s.evidence_ids.map((eid) => evidenceById[eid]?.url ? (
                          <a key={eid} href={evidenceById[eid].url!} target="_blank" rel="noopener noreferrer nofollow"><Badge tone="blue">{eid}</Badge></a>
                        ) : <Badge key={eid} tone="neutral">{eid}</Badge>)}
                      </li>
                    ))}
                    {a.observed_signals.length === 0 ? <li className="text-muted-foreground">—</li> : null}
                  </ul>
                </div>
                <div>
                  <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold"><Lightbulb className="size-3.5 text-sun-500" /> {t.leads.hypotheses}</p>
                  <ul className="space-y-1.5 text-sm">
                    {a.hypotheses.map((h, i) => <li key={i}>{h.statement} <Badge tone="neutral">{h.confidence}</Badge></li>)}
                    {a.potential_problems.map((p, i) => <li key={`p${i}`} className="text-muted-foreground">• {p}</li>)}
                  </ul>
                </div>
                <div>
                  <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold"><CircleHelp className="size-3.5 text-muted-foreground" /> {t.leads.unknowns}</p>
                  <ul className="list-disc space-y-1 ps-5 text-sm text-muted-foreground">
                    {a.unknowns.map((u, i) => <li key={i}>{u}</li>)}
                  </ul>
                </div>
                {a.opportunity ? <p className="rounded-md border-s-4 border-sun-500 bg-muted/50 p-3 text-sm">{a.opportunity}</p> : null}
                {a.suggested_pitch ? <p className="text-sm italic text-muted-foreground">“{a.suggested_pitch}”</p> : null}
              </div>
            )}
          </Section>

          <Section title={t.leads.recommended}>
            {a?.recommended_services.length ? (
              <ul className="space-y-2">
                {a.recommended_services.map((r, i) => (
                  <li key={r.service} className="flex gap-3 rounded-md border p-3">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-sun-500 text-xs font-bold text-navy-900">{i + 1}</span>
                    <div>
                      <p className="text-sm font-medium">{serviceName(r.service)}</p>
                      <p className="text-xs text-muted-foreground">{r.rationale}</p>
                    </div>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-muted-foreground">—</p>}
          </Section>

          <PitchSection lead={lead} />

          {presence.length ? (
            <Section title={t.leads.presence}>
              <ul className="grid gap-2 sm:grid-cols-2">
                {presence.map((e) => (
                  <li key={e.id} className="rounded-md border p-2.5 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{e.title}</span>
                      <Badge tone={e.observed ? "blue" : "neutral"}>{e.observed ? t.leads.observed : t.leads.notAccessible}</Badge>
                    </div>
                    {e.excerpt ? <p className="mt-1 line-clamp-4 whitespace-pre-line text-muted-foreground">{e.excerpt}</p> : null}
                    {e.url ? <a href={e.url} target="_blank" rel="noopener noreferrer nofollow" className="mt-1 inline-block break-all text-primary hover:underline">{e.url}</a> : null}
                  </li>
                ))}
              </ul>
              {fromOsm ? <p className="mt-2 text-[11px] text-muted-foreground">{t.leads.osmAttribution}</p> : null}
            </Section>
          ) : null}

          <Section title={t.leads.evidence}>
            <Tabs defaultValue="signals" dir={locale === "ar" ? "rtl" : "ltr"}>
              <TabsList>
                <TabsTrigger value="signals">{t.leads.signals} ({signals.length})</TabsTrigger>
                <TabsTrigger value="pages">{t.leads.pages} ({pages.length})</TabsTrigger>
              </TabsList>
              <TabsContent value="signals">
                <ul className="grid gap-2 sm:grid-cols-2">
                  {signals.map((e) => (
                    <li key={e.id} className="rounded-md border p-2.5 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{e.title}</span>
                        <Badge tone={e.observed ? "green" : "neutral"}>{e.observed ? t.leads.observed : t.leads.notObserved}</Badge>
                      </div>
                      {e.excerpt ? <p className="mt-1 line-clamp-2 text-muted-foreground">{e.excerpt}</p> : null}
                      {e.url ? <a href={e.url} target="_blank" rel="noopener noreferrer nofollow" className="mt-1 inline-block break-all text-primary hover:underline">{e.url}</a> : null}
                    </li>
                  ))}
                </ul>
              </TabsContent>
              <TabsContent value="pages">
                <ul className="space-y-2">
                  {pages.map((p) => (
                    <li key={p.id} className="rounded-md border p-3 text-xs">
                      <a href={p.url ?? "#"} target="_blank" rel="noopener noreferrer nofollow" className="font-medium text-primary hover:underline">{p.title || p.url}</a>
                      <Badge tone="neutral" className="ms-2">{p.signal_key?.replace("page:", "")}</Badge>
                      <p className="mt-1 line-clamp-3 text-muted-foreground">{p.excerpt}</p>
                    </li>
                  ))}
                </ul>
              </TabsContent>
            </Tabs>
          </Section>
        </div>

        <div className="space-y-4">
          <Section title={t.leads.contactInfo}>
            {lead.contacts.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t.common.notFound}</p>
            ) : (
              <ul className="space-y-2">
                {[...directContacts, ...otherContacts].map((c) => <ContactRow key={c.id} c={c} leadId={id} />)}
              </ul>
            )}
          </Section>

          <Section title={t.leads.scoring}>
            {lead.score ? (
              <div className="space-y-3">
                <div className="flex items-baseline gap-2">
                  <span className="text-3xl font-bold tabular-nums">{lead.score.total}</span>
                  <span className="text-xs text-muted-foreground">/ 100 · v{lead.score.scoring_version}</span>
                </div>
                <ul className="space-y-2">
                  {Object.entries(lead.score.factors).map(([k, v]) => (
                    <li key={k} className="text-xs">
                      <div className="flex justify-between"><span>{label(k)}</span><span className="tabular-nums text-muted-foreground">{Math.round(v * 100)}% × {Math.round((lead.score!.weights[k] ?? 0) * 100)}%</span></div>
                      <div className="mt-1 h-1.5 rounded-full bg-muted"><div className="h-full rounded-full bg-brand-500" style={{ width: `${v * 100}%` }} /></div>
                    </li>
                  ))}
                </ul>
                <ul className="list-disc space-y-1 ps-4 text-[11px] text-muted-foreground">
                  {lead.score.explanation.map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              </div>
            ) : <p className="text-sm text-muted-foreground">{t.leads.notScored}</p>}
          </Section>

          <Section title={t.leads.discovery}>
            <ul className="space-y-2 text-xs">
              {lead.sources.map((s) => (
                <li key={s.id}>
                  <Badge tone="blue">{label(s.provider_key)}</Badge>{" "}
                  <a href={s.source_url} target="_blank" rel="noopener noreferrer nofollow" className="break-all hover:underline">{s.title || s.source_url}</a>
                  <p className="text-muted-foreground">{formatDate(s.discovered_at, locale)}</p>
                </li>
              ))}
            </ul>
          </Section>

          <Section title={t.leads.history}>
            <ul className="space-y-2 text-xs">
              {lead.campaigns.map((c) => (
                <li key={c.id} className="flex items-center justify-between gap-2">
                  <Link href={`/campaigns/${c.id}`} className="truncate hover:underline">{c.name}</Link>
                  <span className="flex items-center gap-1"><ScorePill score={c.score} />{c.qualified ? <CheckCircle2 className="size-3.5 text-success" /> : null}</span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title={t.leads.notes}>
            <form className="mb-3 space-y-2" onSubmit={(e) => { e.preventDefault(); if (note.trim()) addNote.mutate(); }}>
              <Textarea aria-label={t.leads.addNote} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t.leads.addNote} />
              <Button size="sm" type="submit" disabled={!note.trim() || addNote.isPending}>{t.leads.addNote}</Button>
            </form>
            <ul className="space-y-2 text-xs">
              {lead.notes.map((n) => (
                <li key={n.id} className="rounded-md bg-muted/50 p-2"><p className="whitespace-pre-wrap">{n.body}</p><p className="mt-1 text-muted-foreground">{formatDate(n.created_at, locale)}</p></li>
              ))}
              {lead.activities.map((ac) => (
                <li key={ac.id} className="text-muted-foreground">• {label(ac.type)} — {formatDate(ac.created_at, locale)}</li>
              ))}
            </ul>
          </Section>
        </div>
      </div>
    </div>
  );
}
