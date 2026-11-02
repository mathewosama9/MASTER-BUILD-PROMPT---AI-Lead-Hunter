"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, Plus, Save, Sparkles, Wand2, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, Field, Input, Select, Textarea } from "@/components/ui/primitives";
import { ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { OutOfCredits } from "@/features/billing/out-of-credits";
import { useBillingSummary, useMeta, usePlatformAdmin, useProfile, useServiceName } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api, ApiError } from "@/lib/api";
import { cn, humanize } from "@/lib/utils";
import type { Campaign, Profile } from "@/types/api";

import {
  campaignSchema,
  defaultCampaignValues,
  STEP_FIELDS,
  toApiPayload,
  type CampaignFormInput,
  type CampaignFormValues,
} from "./schema";

const LAST_STEP = STEP_FIELDS.length - 1;
const MAX_OFFERINGS = 12; // backend ProfileIn.offerings
const EMPTY_SERVICE = { name: "", description: "" };

interface Estimate {
  providers: Record<string, { status: string; detail: string | null }>;
  estimated_requests: number;
  estimated_cost_usd: number | null;
  notes: string[];
  credits_max: number;
  credit_balance: number | null;
}

export function CampaignWizard() {
  const { t, locale, vmsg } = useI18n();
  const router = useRouter();
  const qc = useQueryClient();
  const meta = useMeta();
  const platformAdmin = usePlatformAdmin();
  const { data: billing } = useBillingSummary();
  const profile = useProfile();
  const nameOf = useServiceName();
  const [step, setStep] = useState(0);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState(EMPTY_SERVICE);

  const form = useForm<CampaignFormInput, unknown, CampaignFormValues>({
    resolver: zodResolver(campaignSchema),
    // Searches default to the language the user works in.
    defaultValues: { ...defaultCampaignValues, language: locale },
    mode: "onTouched",
  });
  const { register, control, formState, setValue, getValues, trigger, handleSubmit } = form;
  const values = useWatch({ control });

  const parse = useMutation({
    mutationFn: (text: string) => api<Record<string, unknown>>("/campaigns/parse-spec", { method: "POST", body: { text } }),
    onSuccess: (spec) => {
      if (typeof spec.industry === "string") setValue("industry", spec.industry, { shouldValidate: true });
      if (typeof spec.country === "string" && spec.country) setValue("country", spec.country);
      if (typeof spec.city === "string" && spec.city) setValue("city", spec.city);
      if (Array.isArray(spec.keywords) && spec.keywords.length) setValue("keywords", spec.keywords.join(", "));
      if (Array.isArray(spec.characteristics) && spec.characteristics.length)
        setValue("characteristics", spec.characteristics.join(", "));
      if (Array.isArray(spec.services)) setValue("services", spec.services as string[]);
      if (spec.language === "ar" || spec.language === "en") setValue("language", spec.language);
      toast.success(spec.parser === "rule_based" ? t.wizard.parsedRules : t.wizard.parsedAi);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  // A new service is saved to the business profile (Settings → Business), then selected for this campaign.
  const addService = useMutation({
    mutationFn: () => {
      const current = profile.data?.offerings ?? [];
      return api<Profile>("/profile", {
        method: "PUT",
        body: { offerings: [...current, { name: draft.name.trim(), description: draft.description.trim(), keywords: [] }] },
      });
    },
    onSuccess: (saved) => {
      qc.setQueryData(["profile"], saved);
      const known = new Set((profile.data?.offerings ?? []).map((o) => o.id));
      const created = saved.offerings.find((o) => !known.has(o.id));
      if (created) setValue("services", [...getValues("services"), created.id].slice(0, 10), { shouldValidate: true });
      setDraft(EMPTY_SERVICE);
      setAdding(false);
      toast.success(t.wizard.serviceAdded);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const submit = useMutation({
    mutationFn: ({ v, start }: { v: CampaignFormValues; start: boolean }) =>
      api<Campaign>("/campaigns", { method: "POST", body: toApiPayload(v, start) }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success(c.status === "draft" ? t.wizard.draftSaved : t.wizard.campaignStarted);
      router.push(`/app/campaigns/${c.id}`);
    },
    onError: (e: Error) => toast.error(e instanceof ApiError ? e.message : String(e)),
  });

  if (meta.isLoading) return <LoadingState rows={6} />;
  if (meta.error) return <ErrorState error={meta.error} />;
  const m = meta.data!;
  const country = m.countries.find((c) => c.code === values.country);
  // A search can't start with no credits left or after the trial ended.
  const noCredits =
    !!billing && !billing.billing_exempt && (billing.balance <= 0 || (billing.on_trial && billing.trial_expired));
  const sep = locale === "ar" ? "، " : ", ";
  const industryName = (k: string | undefined) => {
    const i = m.industries.find((x) => x.key === k);
    return i ? (locale === "ar" ? i.ar : i.en) : humanize(k);
  };
  const offerings = profile.data?.offerings ?? [];
  const serviceName = (k: string | undefined) => (k ? nameOf(k, locale) : humanize(k));

  async function next() {
    const ok = await trigger(STEP_FIELDS[step] as never);
    if (!ok) return;
    if (step === LAST_STEP - 1) {
      if (!getValues("name")) {
        const ind = m.industries.find((i) => i.key === getValues("industry"));
        const place = getValues("city") || (locale === "ar" ? country?.name_ar : country?.name_en) || getValues("country");
        setValue("name", `${(locale === "ar" ? ind?.ar : ind?.en) ?? getValues("industry")} · ${place}`);
      }
      try {
        const parsed = campaignSchema.safeParse(getValues());
        if (parsed.success) {
          setEstimate(await api<Estimate>("/campaigns/estimate", { method: "POST", body: toApiPayload(parsed.data, false) }));
        }
      } catch {
        setEstimate(null);
      }
    }
    setStep((s) => Math.min(s + 1, LAST_STEP));
  }

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title={t.wizard.title} />
      <ol className="mb-6 grid grid-cols-3 gap-2" aria-label={t.common.steps}>
        {t.wizard.steps.map((label, i) => (
          <li key={label}>
            <button
              type="button"
              onClick={() => i < step && setStep(i)}
              className={cn(
                "flex w-full flex-col gap-1.5 text-start text-xs",
                i <= step ? "text-foreground" : "text-muted-foreground",
              )}
              aria-current={i === step ? "step" : undefined}
            >
              <span className={cn("h-1 rounded-full", i < step ? "bg-rasd-500" : i === step ? "bg-sun-500" : "bg-muted")} />
              <span className="flex items-center gap-1 font-medium">
                {i < step ? <Check className="size-3" /> : <span className="tabular-nums">{i + 1}.</span>}
                <span className="hidden sm:inline">{label}</span>
              </span>
            </button>
          </li>
        ))}
      </ol>

      <form onSubmit={handleSubmit((v) => submit.mutate({ v, start: true }))} noValidate>
        <Card>
          <CardContent className="space-y-5 p-6">
            {step === 0 && (
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t.wizard.country} htmlFor="country" error={vmsg(formState.errors.country?.message)}>
                  <Select id="country" {...register("country")}>
                    {m.countries.map((c) => (
                      <option key={c.code} value={c.code}>
                        {locale === "ar" ? c.name_ar : c.name_en}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label={t.wizard.city} htmlFor="city">
                  <Input id="city" list="cities" placeholder={t.wizard.cityPlaceholder} {...register("city")} />
                  <datalist id="cities">
                    {country?.cities.map((c) => (
                      <option key={c.en} value={c.en}>
                        {c.ar}
                      </option>
                    ))}
                  </datalist>
                </Field>
                <Field label={t.wizard.region} htmlFor="region">
                  <Input id="region" {...register("region")} />
                </Field>
                <Field label={t.wizard.language} htmlFor="language">
                  <Select id="language" {...register("language")}>
                    <option value="en">English</option>
                    <option value="ar">العربية</option>
                  </Select>
                </Field>
              </div>
            )}

            {step === 1 && (
              <div className="space-y-4">
                <div className="rounded-lg border border-rasd-500/30 bg-rasd-500/5 p-4">
                  <Field label={t.wizard.nlQuery} htmlFor="nl_query">
                    <Textarea id="nl_query" placeholder={t.wizard.nlPlaceholder} {...register("nl_query")} />
                  </Field>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    className="mt-3"
                    disabled={parse.isPending || (values.nl_query ?? "").length < 3}
                    onClick={() => parse.mutate(getValues("nl_query") ?? "")}
                  >
                    {parse.isPending ? <Spinner /> : <Wand2 />} {t.wizard.parse}
                  </Button>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label={t.wizard.industry} htmlFor="industry" error={vmsg(formState.errors.industry?.message)}>
                    <Input id="industry" list="industries" aria-invalid={!!formState.errors.industry} {...register("industry")} />
                    <datalist id="industries">
                      {m.industries.map((i) => (
                        <option key={i.key} value={i.key}>
                          {locale === "ar" ? i.ar : i.en}
                        </option>
                      ))}
                    </datalist>
                  </Field>
                  <Field label={t.wizard.companySize} htmlFor="company_size">
                    <Select id="company_size" {...register("company_size")}>
                      <option value="">{t.common.all}</option>
                      <option value="1-10">1–10</option>
                      <option value="11-50">11–50</option>
                      <option value="51-200">51–200</option>
                      <option value="201+">201+</option>
                    </Select>
                  </Field>
                  <Field label={t.wizard.keywords} htmlFor="keywords" hint={t.wizard.keywordsHint}>
                    <Input id="keywords" placeholder="orthodontics, تقويم" {...register("keywords")} />
                  </Field>
                  <Field label={t.wizard.excluded} htmlFor="excluded_keywords">
                    <Input id="excluded_keywords" placeholder="jobs, وظائف" {...register("excluded_keywords")} />
                  </Field>
                  <Field label={t.wizard.characteristics} htmlFor="characteristics" className="sm:col-span-2">
                    <Input id="characteristics" placeholder={t.wizard.characteristicsPlaceholder} {...register("characteristics")} />
                  </Field>
                </div>
                <fieldset>
                  <legend className="mb-2 text-xs font-medium">{t.wizard.services}</legend>
                  <Controller
                    control={control}
                    name="services"
                    render={({ field }) => (
                      <div className="flex flex-wrap items-center gap-2">
                        {offerings.map((s) => {
                          const on = field.value.includes(s.id);
                          return (
                            <button
                              type="button"
                              key={s.id}
                              aria-pressed={on}
                              title={s.description || undefined}
                              onClick={() =>
                                field.onChange(on ? field.value.filter((x) => x !== s.id) : [...field.value, s.id])
                              }
                              className={cn(
                                "rounded-full border px-3 py-1 text-xs transition-colors",
                                on ? "border-rasd-500 bg-rasd-500/15 text-foreground" : "hover:bg-muted",
                              )}
                            >
                              {s.name}
                            </button>
                          );
                        })}
                        {!adding ? (
                          <button
                            type="button"
                            onClick={() => setAdding(true)}
                            disabled={offerings.length >= MAX_OFFERINGS}
                            title={offerings.length >= MAX_OFFERINGS ? t.wizard.servicesFull : undefined}
                            className="inline-flex items-center gap-1 rounded-full border border-dashed px-3 py-1 text-xs text-primary hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <Plus className="size-3.5" /> {t.wizard.addService}
                          </button>
                        ) : null}
                      </div>
                    )}
                  />
                  {adding ? (
                    <div className="mt-3 grid gap-3 rounded-lg border p-3 sm:grid-cols-[1fr_1.5fr_auto] sm:items-end">
                      <Field label={t.wizard.newServiceName} htmlFor="new_service_name">
                        <Input
                          id="new_service_name"
                          autoFocus
                          maxLength={120}
                          value={draft.name}
                          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              if (draft.name.trim()) addService.mutate();
                            }
                          }}
                        />
                      </Field>
                      <Field label={t.wizard.newServiceDesc} htmlFor="new_service_desc">
                        <Input
                          id="new_service_desc"
                          maxLength={600}
                          value={draft.description}
                          onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                        />
                      </Field>
                      <div className="flex gap-2">
                        <Button type="button" size="sm" disabled={!draft.name.trim() || addService.isPending} onClick={() => addService.mutate()}>
                          {addService.isPending ? <Spinner /> : <Plus />} {t.wizard.addService}
                        </Button>
                        <Button type="button" size="sm" variant="ghost" aria-label={t.common.cancel} onClick={() => { setAdding(false); setDraft(EMPTY_SERVICE); }}>
                          <X />
                        </Button>
                      </div>
                    </div>
                  ) : null}
                  {!offerings.length && !adding ? (
                    <p className="mt-2 text-xs text-muted-foreground">
                      {t.business.noOfferings}{" "}
                      <Link href="/app/settings" className="text-primary underline">{t.business.tab}</Link>
                    </p>
                  ) : null}
                </fieldset>
                <Field label={t.wizard.targetCount} htmlFor="target_count" hint={t.wizard.targetHint}
                       error={vmsg(formState.errors.target_count?.message)} className="sm:max-w-xs">
                  <Input id="target_count" type="number" inputMode="numeric" min={1} max={500}
                         aria-invalid={!!formState.errors.target_count} {...register("target_count")} />
                </Field>
              </div>
            )}

            {step === LAST_STEP && (
              <div className="space-y-5">
                <Field label={t.wizard.name} htmlFor="name" error={vmsg(formState.errors.name?.message)}>
                  <Input id="name" {...register("name")} />
                </Field>
                <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                  {[
                    [t.wizard.country, `${(locale === "ar" ? country?.name_ar : country?.name_en) ?? values.country}${values.city ? ` · ${values.city}` : ""}`],
                    [t.wizard.industry, industryName(values.industry)],
                    [t.wizard.keywords, values.keywords || "—"],
                    [t.wizard.services, (values.services ?? []).map(serviceName).join(sep) || "—"],
                    [t.wizard.targetCount, String(values.target_count)],
                  ].map(([k, v]) => (
                    <div key={String(k)} className="flex flex-col gap-0.5 border-b pb-2">
                      <dt className="text-xs text-muted-foreground">{k}</dt>
                      <dd>{String(v)}</dd>
                    </div>
                  ))}
                </dl>
                {estimate && (estimate.credits_max > 0 || platformAdmin) ? (
                  <div className="rounded-lg border bg-muted/50 p-4 text-sm">
                    {estimate.credits_max > 0 ? (
                      <p className="font-medium">
                        {t.wizard.creditsUpTo
                          .replace("{n}", String(estimate.credits_max))
                          .replace("{b}", String(estimate.credit_balance ?? 0))}
                      </p>
                    ) : null}
                    {/* Providers, costs and caps are the platform's business: the server sends them to admins only. */}
                    {platformAdmin ? (
                      <div className="mt-2 text-xs text-muted-foreground">
                        <p>
                          ~{estimate.estimated_requests} {t.wizard.providerRequests} ·{" "}
                          {estimate.estimated_cost_usd !== null ? `~$${estimate.estimated_cost_usd}` : "—"}
                        </p>
                        <ul className="mt-1 list-disc space-y-1 ps-5">
                          {estimate.notes.map((n) => (
                            <li key={n}>{n}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <OutOfCredits />
              </div>
            )}
          </CardContent>
        </Card>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <Button type="button" variant="ghost" onClick={() => (step === 0 ? router.push("/app/campaigns") : setStep(step - 1))}>
            <ChevronLeft className="rtl:rotate-180" /> {step === 0 ? t.common.cancel : t.common.back}
          </Button>
          {step < LAST_STEP ? (
            <Button type="button" onClick={next}>
              {t.common.next} <ChevronRight className="rtl:rotate-180" />
            </Button>
          ) : (
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={submit.isPending}
                onClick={handleSubmit((v) => submit.mutate({ v, start: false }))}
              >
                <Save /> {t.wizard.saveDraft}
              </Button>
              <Button type="submit" variant="accent" disabled={submit.isPending || noCredits}>
                {submit.isPending ? <Spinner /> : <Sparkles />} {t.wizard.startCampaign}
              </Button>
            </div>
          )}
        </div>
      </form>
    </div>
  );
}
