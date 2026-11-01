"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Field, Input, Select, Textarea } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useMeta, useProfile } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import type { Offering, Profile } from "@/types/api";

const TONES = ["professional", "friendly", "concise", "consultative"];
const CHANNELS = ["whatsapp", "email", "phone", "linkedin"];

const splitList = (v: string) => v.split(/[,،\n]/).map((x) => x.trim()).filter(Boolean);
const joinList = (v: string[]) => v.join("، ");

export function BusinessProfileTab({ canEdit }: { canEdit: boolean }) {
  const { data, isLoading, error } = useProfile();
  if (isLoading) return <LoadingState />;
  if (error || !data) return <ErrorState error={error} />;
  // Keyed by the loaded data so the form re-initialises from server state without effects.
  return <BusinessProfileForm key={JSON.stringify(data)} data={data} canEdit={canEdit} />;
}

type Draft = Omit<Profile, "onboarding" | "offerings"> & { offerings: (Omit<Offering, "id"> & { id?: string })[] };

function BusinessProfileForm({ data, canEdit }: { data: Profile; canEdit: boolean }) {
  const { t, label, locale } = useI18n();
  const b = t.business;
  const meta = useMeta();
  const qc = useQueryClient();
  const [form, setForm] = useState<Draft>({ ...data, website: data.website ?? "" });
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setForm((f) => ({ ...f, [k]: v }));
  const save = useMutation({
    mutationFn: () => api<Profile>("/profile", { method: "PUT", body: { ...form, website: form.website || null } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile"] });
      toast.success(t.common.saved);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const categories = meta.data?.provider_categories ?? [];
  const industries = meta.data?.industries ?? [];
  const category = categories.find((c) => c.key === form.business_category);
  const industryName = (k: string) => {
    const i = industries.find((x) => x.key === k);
    return i ? (locale === "ar" ? i.ar : i.en) : k;
  };

  function suggest() {
    if (!category) return;
    const have = new Set(form.offerings.map((o) => o.name.toLowerCase()));
    const fresh = category.offerings
      .map((o) => (locale === "ar" ? o.ar : o.en))
      .filter((name) => !have.has(name.toLowerCase()))
      .map((name) => ({ name, description: "", keywords: [] }));
    set("offerings", [...form.offerings, ...fresh].slice(0, 12));
    if (!form.target_industries.length) set("target_industries", category.targets);
  }

  const offering = (i: number, patch: Partial<Draft["offerings"][number]>) =>
    set("offerings", form.offerings.map((o, j) => (j === i ? { ...o, ...patch } : o)));

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{b.title}</CardTitle>
          <CardDescription>{b.hint}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label={b.company} htmlFor="bp-company">
            <Input id="bp-company" disabled={!canEdit} value={form.company_name} onChange={(e) => set("company_name", e.target.value)} />
          </Field>
          <Field label={b.website} htmlFor="bp-website">
            <Input id="bp-website" dir="ltr" disabled={!canEdit} value={form.website ?? ""} onChange={(e) => set("website", e.target.value)} />
          </Field>
          <Field label={b.category} htmlFor="bp-category">
            <Select id="bp-category" disabled={!canEdit} value={form.business_category ?? ""} onChange={(e) => set("business_category", e.target.value || null)}>
              <option value="">—</option>
              {categories.map((c) => <option key={c.key} value={c.key}>{locale === "ar" ? c.ar : c.en}</option>)}
            </Select>
          </Field>
          <div className="sm:col-span-2 grid gap-4 sm:grid-cols-2">
            <Field label={b.description} htmlFor="bp-desc">
              <Textarea id="bp-desc" rows={3} disabled={!canEdit} value={form.description} onChange={(e) => set("description", e.target.value)} />
            </Field>
            <Field label={b.valueProp} htmlFor="bp-value">
              <Textarea id="bp-value" rows={3} disabled={!canEdit} value={form.value_proposition} onChange={(e) => set("value_proposition", e.target.value)} />
            </Field>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{b.offerings}</CardTitle>
          <CardDescription>{b.offeringsHint}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {form.offerings.map((o, i) => (
            <div key={o.id ?? `new-${i}`} className="grid gap-2 rounded-md border p-3 sm:grid-cols-[1fr_1.4fr_1fr_auto]">
              <Input aria-label={b.offeringName} placeholder={b.offeringName} disabled={!canEdit} value={o.name} onChange={(e) => offering(i, { name: e.target.value })} />
              <Input aria-label={b.offeringDesc} placeholder={b.offeringDesc} disabled={!canEdit} value={o.description} onChange={(e) => offering(i, { description: e.target.value })} />
              <Input aria-label={b.keywords} placeholder={b.keywords} disabled={!canEdit} value={joinList(o.keywords)} onChange={(e) => offering(i, { keywords: splitList(e.target.value) })} />
              {canEdit ? (
                <Button variant="ghost" size="sm" aria-label={b.remove} onClick={() => set("offerings", form.offerings.filter((_, j) => j !== i))}>
                  <Trash2 />
                </Button>
              ) : null}
            </div>
          ))}
          {canEdit ? (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" disabled={form.offerings.length >= 12} onClick={() => set("offerings", [...form.offerings, { name: "", description: "", keywords: [] }])}>
                <Plus /> {b.addOffering}
              </Button>
              {category?.offerings.length ? (
                <Button variant="ghost" size="sm" onClick={suggest}><Sparkles /> {b.useTemplates}</Button>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{b.icp}</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label={b.industries} htmlFor="bp-industry">
            <div className="space-y-2">
              <div className="flex flex-wrap gap-1.5">
                {form.target_industries.map((k) => (
                  <button key={k} type="button" disabled={!canEdit}
                          onClick={() => set("target_industries", form.target_industries.filter((x) => x !== k))}
                          className="rounded-full border px-2.5 py-0.5 text-xs hover:bg-muted">
                    {industryName(k)} ×
                  </button>
                ))}
              </div>
              <Select id="bp-industry" disabled={!canEdit} value="" onChange={(e) => e.target.value && set("target_industries", [...new Set([...form.target_industries, e.target.value])])}>
                <option value="">{b.pickIndustry}</option>
                {industries.map((i) => <option key={i.key} value={i.key}>{locale === "ar" ? i.ar : i.en}</option>)}
              </Select>
            </div>
          </Field>
          <ListField id="bp-countries" label={b.countries} hint={b.listHint} value={form.target_countries} disabled={!canEdit} onChange={(v) => set("target_countries", v.map((x) => x.toUpperCase()))} />
          <ListField id="bp-cities" label={b.cities} hint={b.listHint} value={form.target_cities} disabled={!canEdit} onChange={(v) => set("target_cities", v)} />
          <ListField id="bp-sizes" label={b.sizes} hint={b.listHint} value={form.company_sizes} disabled={!canEdit} onChange={(v) => set("company_sizes", v)} />
          <ListField id="bp-good" label={b.goodSignals} hint={b.listHint} value={form.good_signals} disabled={!canEdit} onChange={(v) => set("good_signals", v)} />
          <ListField id="bp-bad" label={b.disqualifiers} hint={b.listHint} value={form.disqualifiers} disabled={!canEdit} onChange={(v) => set("disqualifiers", v)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{b.outreach}</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label={b.senderName} htmlFor="bp-sender">
            <Input id="bp-sender" disabled={!canEdit} value={form.sender_name} onChange={(e) => set("sender_name", e.target.value)} />
          </Field>
          <Field label={b.language} htmlFor="bp-lang">
            <Select id="bp-lang" disabled={!canEdit} value={form.outreach_language} onChange={(e) => set("outreach_language", e.target.value as "ar" | "en")}>
              <option value="ar">العربية</option>
              <option value="en">English</option>
            </Select>
          </Field>
          <Field label={b.tone} htmlFor="bp-tone">
            <Select id="bp-tone" disabled={!canEdit} value={form.tone} onChange={(e) => set("tone", e.target.value)}>
              {TONES.map((x) => <option key={x} value={x}>{label(x)}</option>)}
            </Select>
          </Field>
          <fieldset>
            <legend className="mb-2 text-xs font-medium">{b.channels}</legend>
            <div className="flex flex-wrap gap-2">
              {CHANNELS.map((c) => {
                const on = form.channels.includes(c);
                return (
                  <button key={c} type="button" aria-pressed={on} disabled={!canEdit}
                          onClick={() => set("channels", on ? form.channels.filter((x) => x !== c) : [...form.channels, c])}
                          className={`rounded-full border px-3 py-1 text-xs ${on ? "border-rasd-500 bg-rasd-500/15" : "hover:bg-muted"}`}>
                    {label(c)}
                  </button>
                );
              })}
            </div>
          </fieldset>
        </CardContent>
      </Card>

      {canEdit ? (
        <Button onClick={() => save.mutate()} disabled={save.isPending || form.offerings.some((o) => !o.name.trim())}>
          {t.common.save}
        </Button>
      ) : null}
    </div>
  );
}

function ListField({
  id, label, hint, value, disabled, onChange,
}: { id: string; label: string; hint: string; value: string[]; disabled: boolean; onChange: (v: string[]) => void }) {
  // Kept as typed while editing; the list is derived on every change.
  const [text, setText] = useState(joinList(value));
  return (
    <Field label={label} htmlFor={id} hint={hint}>
      <Input id={id} disabled={disabled} value={text} onChange={(e) => { setText(e.target.value); onChange(splitList(e.target.value)); }} />
    </Field>
  );
}
