"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, Sparkles, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/primitives";
import { ErrorState, LoadingState, Spinner } from "@/components/ui/states";
import { RadarBackdrop } from "@/features/site/motion";
import { useMeta, useProfile } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Campaign, Profile } from "@/types/api";

// Mirrors FIRST_SEARCH_SETTINGS.target_count in backend/app/api/v1/profile.py.
const FIRST_SEARCH_TARGET = 15;

interface Draft {
  category: string | null;
  services: string[];
  industries: string[];
  country: string;
  city: string;
}

/**
 * First-run onboarding: what you sell → who and where → run a small first search, so a new user sees real
 * leads within minutes. Answers are saved to the workspace profile after every step.
 */
export function Welcome() {
  const profile = useProfile();
  const meta = useMeta();
  if (profile.isLoading || meta.isLoading) return <LoadingState rows={6} />;
  if (!profile.data || !meta.data) return <ErrorState error={profile.error ?? meta.error} />;
  return <WelcomeFlow profile={profile.data} />;
}

function WelcomeFlow({ profile }: { profile: Profile }) {
  const { t, locale } = useI18n();
  const w = t.welcome;
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const m = useMeta().data!;
  const categories = m.provider_categories ?? [];
  const local = (x: { en: string; ar: string }) => (locale === "ar" ? x.ar : x.en);
  const industryName = (k: string) => {
    const i = m.industries.find((x) => x.key === k);
    return i ? local(i) : k;
  };

  const [step, setStep] = useState(() => Math.min(profile.onboarding.step, 2));
  const [notice, setNotice] = useState<string | null>(null);
  const [extra, setExtra] = useState("");
  const [draft, setDraft] = useState<Draft>(() => {
    // A category picked on the public site (/register?category=…) is preselected.
    const fromSite = params.get("category");
    const category = profile.business_category ?? (categories.some((c) => c.key === fromSite) ? fromSite : null);
    const preset = categories.find((c) => c.key === category);
    return {
      category,
      services: profile.offerings.length ? profile.offerings.map((o) => o.name) : (preset?.offerings.map(local) ?? []),
      industries: profile.target_industries.length ? profile.target_industries : (preset?.targets ?? []),
      country: profile.target_countries[0] ?? (locale === "ar" ? "EG" : "AE"),
      city: profile.target_cities[0] ?? "",
    };
  });
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const country = m.countries.find((c) => c.code === draft.country);

  function pickCategory(key: string) {
    const c = categories.find((x) => x.key === key);
    // Switching category swaps in its suggestions; the user can still edit them.
    set({ category: key, services: c?.offerings.map(local) ?? [], industries: c?.targets ?? [] });
    setNotice(null);
  }

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<Profile>("/profile", { method: "PUT", body }),
    onSuccess: (data) => qc.setQueryData(["profile"], data),
  });

  async function next() {
    setNotice(null);
    if (step === 0) {
      if (!draft.category) return setNotice(w.pickCategory);
      const keep = new Map(profile.offerings.map((o) => [o.name, o]));
      await save.mutateAsync({
        business_category: draft.category,
        offerings: draft.services.map((name) => keep.get(name) ?? { name, description: "", keywords: [] }),
        onboarding_step: 1,
      });
    } else if (step === 1) {
      if (!draft.industries.length) return setNotice(w.pickIndustry);
      await save.mutateAsync({
        target_industries: draft.industries,
        target_countries: [draft.country],
        target_cities: draft.city ? [draft.city] : [],
        outreach_language: locale,
        onboarding_step: 2,
      });
    }
    setStep((s) => s + 1);
  }

  const run = useMutation({
    mutationFn: () => api<Campaign>("/profile/first-search", { method: "POST" }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["profile"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      router.replace(`/app/campaigns/${c.id}`);
    },
    onError: (e: Error) => {
      if (e instanceof ApiError && e.code === "email_unverified") setNotice(w.verifyFirst);
      else if (e instanceof ApiError && e.code === "no_sources") setNotice(w.noSources);
      else toast.error(e.message);
    },
  });

  async function skip() {
    await save.mutateAsync({ onboarding_completed: true });
    router.replace("/app");
  }

  const busy = save.isPending || run.isPending;
  const countryLabel = country ? local({ en: country.name_en, ar: country.name_ar }) : draft.country;
  const city = country?.cities.find((c) => c.en === draft.city);
  const place = draft.city ? [city ? local(city) : draft.city, countryLabel].join(locale === "ar" ? "، " : ", ") : countryLabel;

  return (
    <div className="mx-auto max-w-3xl space-y-6 py-2 md:py-6">
      <div className="relative overflow-hidden rounded-2xl bg-ink-900 p-6 text-paper md:p-8">
        <RadarBackdrop onDark className="-top-40 end-[-10rem] size-[30rem]" />
        <div className="relative">
          <p className="text-xs font-semibold text-signal-400">{w.stepOf.replace("{n}", String(step + 1))}</p>
          <h1 className="mt-2 font-display text-2xl font-bold tracking-tight md:text-3xl">{w.title}</h1>
          <p className="mt-2 max-w-xl text-mist-300">{w.subtitle}</p>
          <div className="mt-5 flex gap-2" aria-hidden>
            {[0, 1, 2].map((i) => (
              <span key={i} className={cn("h-1.5 flex-1 rounded-full", i <= step ? "bg-signal-400" : "bg-white/15")} />
            ))}
          </div>
        </div>
      </div>

      <section className="rounded-2xl border bg-card p-6 md:p-8">
        {step === 0 ? (
          <>
            <h2 className="text-xl font-semibold">{w.sellTitle}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{w.sellHint}</p>
            <div className="mt-5 grid gap-2 sm:grid-cols-2">
              {categories.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  onClick={() => pickCategory(c.key)}
                  aria-pressed={draft.category === c.key}
                  className={cn(
                    "flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-start text-sm font-medium transition-colors",
                    draft.category === c.key ? "border-rasd-500 bg-rasd-500/10" : "hover:bg-muted",
                  )}
                >
                  {local(c)}
                  {draft.category === c.key ? <Check className="size-4 shrink-0 text-rasd-600" aria-hidden /> : null}
                </button>
              ))}
            </div>
            {draft.category ? (
              <div className="mt-6">
                <p className="text-sm font-medium">{w.servicesLabel}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {draft.services.map((s) => (
                    <span key={s} className="inline-flex items-center gap-1 rounded-full bg-rasd-100 py-1 pe-1.5 ps-3 text-sm text-rasd-800 dark:bg-rasd-500/15 dark:text-rasd-200">
                      {s}
                      <button
                        type="button"
                        aria-label={`${t.business.remove}: ${s}`}
                        onClick={() => set({ services: draft.services.filter((x) => x !== s) })}
                        className="rounded-full p-0.5 hover:bg-rasd-200 dark:hover:bg-rasd-500/25"
                      >
                        <X className="size-3.5" aria-hidden />
                      </button>
                    </span>
                  ))}
                </div>
                <form
                  className="mt-3 flex gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const v = extra.trim();
                    if (v && !draft.services.includes(v)) set({ services: [...draft.services, v].slice(0, 12) });
                    setExtra("");
                  }}
                >
                  <Input aria-label={w.addServicePlaceholder} placeholder={w.addServicePlaceholder} value={extra} onChange={(e) => setExtra(e.target.value)} />
                  <Button type="submit" variant="outline" disabled={!extra.trim()}>
                    <Plus /> {w.addService}
                  </Button>
                </form>
              </div>
            ) : null}
          </>
        ) : step === 1 ? (
          <>
            <h2 className="text-xl font-semibold">{w.whoTitle}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{w.whoHint}</p>
            <div className="mt-5 flex flex-wrap gap-2">
              {draft.industries.map((k, i) => (
                <span
                  key={k}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full py-1 pe-1.5 ps-3 text-sm",
                    i === 0 ? "bg-ink-900 text-paper" : "bg-muted",
                  )}
                >
                  {industryName(k)}
                  <button
                    type="button"
                    aria-label={`${t.business.remove}: ${industryName(k)}`}
                    onClick={() => set({ industries: draft.industries.filter((x) => x !== k) })}
                    className="rounded-full p-0.5 hover:bg-black/10 dark:hover:bg-white/10"
                  >
                    <X className="size-3.5" aria-hidden />
                  </button>
                </span>
              ))}
            </div>
            <Select
              aria-label={w.moreIndustries}
              className="mt-3 max-w-sm"
              value=""
              onChange={(e) => e.target.value && set({ industries: [...draft.industries, e.target.value].slice(0, 30) })}
            >
              <option value="">{w.moreIndustries}</option>
              {m.industries
                .filter((i) => !draft.industries.includes(i.key))
                .map((i) => (
                  <option key={i.key} value={i.key}>
                    {local(i)}
                  </option>
                ))}
            </Select>
            <div className="mt-6 grid gap-4 sm:grid-cols-2">
              <Field label={w.country} htmlFor="wl-country">
                <Select id="wl-country" value={draft.country} onChange={(e) => set({ country: e.target.value, city: "" })}>
                  {m.countries.map((c) => (
                    <option key={c.code} value={c.code}>
                      {local({ en: c.name_en, ar: c.name_ar })}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={w.city} htmlFor="wl-city">
                <Select id="wl-city" value={draft.city} onChange={(e) => set({ city: e.target.value })}>
                  <option value="">{w.cityAll}</option>
                  {country?.cities.map((c) => (
                    <option key={c.en} value={c.en}>
                      {local(c)}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
          </>
        ) : (
          <>
            <h2 className="text-xl font-semibold">{w.readyTitle}</h2>
            <p className="mt-3 text-lg leading-relaxed">
              {w.readyBody
                .replace("{industry}", industryName(draft.industries[0] ?? ""))
                .replace("{place}", place)
                .replace("{n}", String(FIRST_SEARCH_TARGET))}
            </p>
            <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
              <li className="flex gap-2">
                <Check className="mt-0.5 size-4 shrink-0 text-rasd-600" aria-hidden />
                {w.readyCost.replace("{n}", String(FIRST_SEARCH_TARGET))}
              </li>
              <li className="flex gap-2">
                <Check className="mt-0.5 size-4 shrink-0 text-rasd-600" aria-hidden />
                {w.readyTime}
              </li>
            </ul>
          </>
        )}

        {notice ? (
          <p role="alert" className="mt-5 rounded-md bg-warning/10 px-3 py-2 text-sm text-foreground">
            {notice}
          </p>
        ) : null}

        <div className="mt-8 flex flex-wrap items-center gap-3">
          {step > 0 ? (
            <Button variant="ghost" onClick={() => {
                setNotice(null);
                setStep((s) => s - 1);
              }} disabled={busy}>
              {w.back}
            </Button>
          ) : null}
          <div className="ms-auto flex flex-wrap items-center gap-3">
            <Button variant="link" onClick={skip} disabled={busy}>
              {w.skip}
            </Button>
            {step < 2 ? (
              <Button variant="ink" size="lg" onClick={() => next().catch((e: Error) => toast.error(e.message))} disabled={busy}>
                {save.isPending ? <Spinner /> : null}
                {w.next}
              </Button>
            ) : (
              <Button variant="accent" size="lg" onClick={() => run.mutate()} disabled={busy}>
                {run.isPending ? <Spinner /> : <Sparkles />}
                {w.run}
              </Button>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
