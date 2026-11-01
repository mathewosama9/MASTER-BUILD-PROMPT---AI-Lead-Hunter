"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Eye, EyeOff, Pencil, Plus, Star, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, Dialog, Field, Input, Select, Switch, Textarea } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";
import type { PublicTestimonial } from "@/types/api";

type Status = "pending" | "approved" | "hidden";
type Source = "sample" | "in_app" | "manual";

interface AdminTestimonial extends PublicTestimonial {
  source: Source;
  status: Status;
  sort: number;
  consent_publish: boolean;
  workspace_id: string | null;
  user_id: string | null;
  created_at: string;
  reviewed_at: string | null;
}

type Draft = {
  author_name: string;
  author_role: string;
  company: string;
  city: string;
  country: string;
  rating: number;
  body_ar: string;
  body_en: string;
  status: Status;
  is_featured: boolean;
  sort: number;
};

const EMPTY: Draft = {
  author_name: "",
  author_role: "",
  company: "",
  city: "",
  country: "",
  rating: 5,
  body_ar: "",
  body_en: "",
  status: "approved",
  is_featured: false,
  sort: 0,
};

const TONE: Record<Status, "yellow" | "green" | "neutral"> = { pending: "yellow", approved: "green", hidden: "neutral" };
const onError = (e: Error) => toast.error(e.message);

function Editor({ initial, id, onClose }: { initial: Draft; id: string | null; onClose: () => void }) {
  const { t } = useI18n();
  const r = t.admin.reviews;
  const qc = useQueryClient();
  const [d, setD] = useState<Draft>(initial);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...d,
        author_role: d.author_role || null,
        company: d.company || null,
        city: d.city || null,
        country: d.country ? d.country.toUpperCase() : null,
      };
      return id
        ? api(`/admin/testimonials/${id}`, { method: "PATCH", body })
        : api("/admin/testimonials", { method: "POST", body });
    },
    onSuccess: () => {
      toast.success(t.common.saved);
      void qc.invalidateQueries({ queryKey: ["admin-testimonials"] });
      void qc.invalidateQueries({ queryKey: ["admin-overview"] });
      onClose();
    },
    onError,
  });
  return (
    <Dialog
      open
      wide
      onOpenChange={(o) => !o && onClose()}
      title={id ? r.editTitle : r.addTitle}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t.common.cancel}
          </Button>
          <Button
            variant="ink"
            disabled={d.author_name.trim().length < 2 || !(d.body_ar.trim() || d.body_en.trim()) || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? <Spinner /> : null} {t.common.save}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={r.author} htmlFor="tm_author">
          <Input id="tm_author" value={d.author_name} onChange={(e) => set("author_name", e.target.value)} />
        </Field>
        <Field label={r.role} htmlFor="tm_role">
          <Input id="tm_role" value={d.author_role} onChange={(e) => set("author_role", e.target.value)} />
        </Field>
        <Field label={r.company} htmlFor="tm_company">
          <Input id="tm_company" value={d.company} onChange={(e) => set("company", e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label={r.city} htmlFor="tm_city">
            <Input id="tm_city" value={d.city} onChange={(e) => set("city", e.target.value)} />
          </Field>
          <Field label={r.country} htmlFor="tm_country">
            <Input id="tm_country" dir="ltr" maxLength={2} value={d.country} onChange={(e) => set("country", e.target.value)} />
          </Field>
        </div>
        <Field label={r.bodyAr} htmlFor="tm_ar" className="sm:col-span-2">
          <Textarea id="tm_ar" dir="rtl" rows={3} value={d.body_ar} onChange={(e) => set("body_ar", e.target.value)} />
        </Field>
        <Field label={r.bodyEn} htmlFor="tm_en" className="sm:col-span-2">
          <Textarea id="tm_en" dir="ltr" rows={3} value={d.body_en} onChange={(e) => set("body_en", e.target.value)} />
        </Field>
        <Field label={r.rating} htmlFor="tm_rating">
          <Select id="tm_rating" value={d.rating} onChange={(e) => set("rating", Number(e.target.value))}>
            {[5, 4, 3, 2, 1].map((n) => (
              <option key={n} value={n}>
                {"★".repeat(n)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={r.status} htmlFor="tm_status">
          <Select id="tm_status" value={d.status} onChange={(e) => set("status", e.target.value as Status)}>
            {(["approved", "pending", "hidden"] as const).map((s) => (
              <option key={s} value={s}>
                {r.statuses[s]}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t.admin.sort} htmlFor="tm_sort" hint={t.admin.sortHint}>
          <Input id="tm_sort" type="number" min={0} value={d.sort} onChange={(e) => set("sort", Number(e.target.value))} />
        </Field>
        <label className="flex items-center gap-3 self-end pb-2 text-sm">
          <Switch checked={d.is_featured} onCheckedChange={(v) => set("is_featured", v)} aria-label={t.admin.featured} />
          {t.admin.featured}
        </label>
      </div>
    </Dialog>
  );
}

export function TestimonialsAdmin() {
  const { t, locale } = useI18n();
  const r = t.admin.reviews;
  const qc = useQueryClient();
  const [editing, setEditing] = useState<{ id: string | null; draft: Draft } | null>(null);
  const q = useQuery({ queryKey: ["admin-testimonials"], queryFn: () => api<AdminTestimonial[]>("/admin/testimonials") });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["admin-testimonials"] });
    void qc.invalidateQueries({ queryKey: ["admin-overview"] });
  };
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Draft> }) => api(`/admin/testimonials/${id}`, { method: "PATCH", body }),
    onSuccess: refresh,
    onError,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/admin/testimonials/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError,
  });

  if (q.isLoading) return <LoadingState rows={4} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const samples = q.data.filter((x) => x.source === "sample" && x.status === "approved").length;

  return (
    <div className="space-y-4">
      {samples > 0 ? (
        <p className="flex items-start gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-800 dark:text-rose-200">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden /> {r.sampleWarning}
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button variant="ink" onClick={() => setEditing({ id: null, draft: EMPTY })}>
          <Plus /> {r.add}
        </Button>
      </div>
      {q.data.length === 0 ? (
        <EmptyState title={r.empty} />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {q.data.map((x) => {
            const body = locale === "ar" ? x.body_ar || x.body_en : x.body_en || x.body_ar;
            const blocked = x.source === "in_app" && !x.consent_publish;
            return (
              <Card key={x.id} className={cn(x.status === "hidden" && "opacity-60")}>
                <CardContent className="space-y-3 p-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={TONE[x.status]}>{r.statuses[x.status]}</Badge>
                    <Badge tone={x.source === "sample" ? "red" : "neutral"}>{r.sources[x.source]}</Badge>
                    {x.is_featured ? <Badge tone="blue">{t.admin.featured}</Badge> : null}
                    {blocked ? <Badge tone="yellow">{r.noConsent}</Badge> : null}
                    <span className="ms-auto inline-flex" aria-label={String(x.rating)}>
                      {[1, 2, 3, 4, 5].map((i) => (
                        <Star key={i} className={cn("size-3.5", i <= x.rating ? "fill-sun-500 text-sun-500" : "text-muted-foreground/30")} />
                      ))}
                    </span>
                  </div>
                  <p className="text-sm leading-relaxed">{body}</p>
                  <p className="text-xs text-muted-foreground">
                    {[x.author_name, x.author_role, x.company, x.city].filter(Boolean).join(" · ")} · {formatDate(x.created_at, locale)}
                  </p>
                  <div className="flex flex-wrap gap-1.5 border-t pt-3">
                    {x.status !== "approved" ? (
                      <Button size="sm" variant="outline" disabled={blocked || patch.isPending} onClick={() => patch.mutate({ id: x.id, body: { status: "approved" } })}>
                        <Eye /> {r.approve}
                      </Button>
                    ) : (
                      <Button size="sm" variant="outline" disabled={patch.isPending} onClick={() => patch.mutate({ id: x.id, body: { status: "hidden" } })}>
                        <EyeOff /> {r.hide}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setEditing({
                          id: x.id,
                          draft: {
                            author_name: x.author_name,
                            author_role: x.author_role ?? "",
                            company: x.company ?? "",
                            city: x.city ?? "",
                            country: x.country ?? "",
                            rating: x.rating,
                            body_ar: x.body_ar,
                            body_en: x.body_en,
                            status: x.status,
                            is_featured: x.is_featured,
                            sort: x.sort,
                          },
                        })
                      }
                    >
                      <Pencil /> {t.admin.edit}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="ms-auto text-destructive"
                      disabled={remove.isPending}
                      onClick={() => window.confirm(r.deleteConfirm) && remove.mutate(x.id)}
                    >
                      <Trash2 /> {r.delete}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
      {editing ? <Editor initial={editing.draft} id={editing.id} onClose={() => setEditing(null)} /> : null}
    </div>
  );
}
