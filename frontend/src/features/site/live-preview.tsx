"use client";

import { useQuery } from "@tanstack/react-query";
import { Mail, MessageCircle, Phone, UserRound } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn, formatDate, formatNumber } from "@/lib/utils";

import { ScoreBadge } from "./mockups";
import { Ping, RadarBackdrop } from "./motion";
import { ForwardArrow, Heading, Section } from "./parts";

interface Place {
  country: string;
  city: string | null;
  count: number;
}
interface PreviewOptions {
  categories: { key: string; en: string; ar: string; places: Place[] }[];
}
interface Preview {
  count: number;
  searched_at: string | null;
  samples: { name: string; city: string | null; score: number | null; reason: string; contact_types: string[] }[];
}

const CONTACT_ICONS: Record<string, typeof Phone> = { whatsapp: MessageCircle, phone: Phone, email: Mail, person: UserRound };

/**
 * "What would Rasd find for me?" from real searches the platform ran in its showcase workspace: a real count and
 * three masked businesses. Falls back to the illustrative examples while there is no showcase data.
 */
export function LivePreview({ fallback, category: only }: { fallback: React.ReactNode; category?: string }) {
  const { t, locale } = useI18n();
  const h = t.site.home;
  const opts = useQuery({
    queryKey: ["public-preview-options"],
    queryFn: () => api<PreviewOptions>("/public/preview/options"),
    staleTime: 5 * 60_000,
  });
  const categories = (opts.data?.categories ?? []).filter((c) => !only || c.key === only);
  const [picked, setPicked] = useState<string | null>(null);
  const [placeIdx, setPlaceIdx] = useState(0);
  const cat = categories.find((c) => c.key === picked) ?? categories[0];
  const place = cat?.places[Math.min(placeIdx, cat.places.length - 1)];
  const preview = useQuery({
    queryKey: ["public-preview", cat?.key, place?.country, place?.city],
    queryFn: () =>
      api<Preview>("/public/preview", { query: { category: cat!.key, country: place!.country, city: place!.city ?? undefined } }),
    enabled: !!cat && !!place,
    staleTime: 5 * 60_000,
  });

  if (!cat || !place) return <>{fallback}</>;

  const regions = new Intl.DisplayNames([locale], { type: "region" });
  const placeName = (p: Place) => [p.city, regions.of(p.country)].filter(Boolean).join(locale === "ar" ? "، " : ", ");
  const data = preview.data;

  return (
    <Section tone="ink">
      <RadarBackdrop onDark className="-top-80 start-[-20rem] size-[48rem]" />
      <Heading title={h.tryTitle} subtitle={h.liveSubtitle} onDark />
      <div className="mx-auto max-w-5xl">
        {categories.length > 1 ? (
          <div className="flex flex-wrap items-center justify-center gap-2" role="group" aria-label={h.tryLabel}>
            <span className="me-1 text-sm text-mist-300">{h.tryLabel}</span>
            {categories.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={() => {
                  setPicked(c.key);
                  setPlaceIdx(0);
                }}
                aria-pressed={c.key === cat.key}
                className={cn(
                  "rounded-full border px-4 py-2 text-sm font-medium transition-colors",
                  c.key === cat.key
                    ? "border-signal-400 bg-signal-400 text-ink-900"
                    : "border-white/15 text-paper hover:border-white/30 hover:bg-white/5",
                )}
              >
                {locale === "ar" ? c.ar : c.en}
              </button>
            ))}
          </div>
        ) : null}
        {cat.places.length > 1 ? (
          <div className="mt-4 flex justify-center">
            <label className="flex items-center gap-2 text-sm text-mist-300">
              {h.livePlace}
              <select
                value={Math.min(placeIdx, cat.places.length - 1)}
                onChange={(e) => setPlaceIdx(Number(e.target.value))}
                className="rounded-md border border-white/15 bg-ink-800 px-3 py-1.5 text-paper"
              >
                {cat.places.map((p, i) => (
                  <option key={`${p.country}-${p.city}`} value={i}>
                    {placeName(p)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}

        <div className="mt-10 grid gap-4 md:grid-cols-[1fr_1.6fr]">
          <div className="flex flex-col justify-between rounded-2xl border border-white/10 bg-white/[0.04] p-6">
            <div>
              <p className="flex items-center gap-2 text-xs font-semibold text-mist-300">
                <Ping className="size-2" /> {placeName(place)}
              </p>
              <p className="mt-4 font-display text-6xl font-bold tracking-tight text-signal-400 tabular-nums">
                {formatNumber(data?.count ?? place.count, locale)}
              </p>
              <p className="mt-2 text-lg font-medium">{h.liveCount}</p>
              {data?.searched_at ? (
                <p className="mt-4 text-sm leading-relaxed text-mist-300">
                  {h.liveNote.replace("{place}", placeName(place)).replace("{date}", formatDate(data.searched_at, locale))}
                </p>
              ) : null}
            </div>
            <Button asChild variant="accent" className="mt-6">
              <Link href={`/register?category=${cat.key}`}>
                {h.liveCta} <ForwardArrow />
              </Link>
            </Button>
          </div>
          <ul className="space-y-3" aria-busy={preview.isLoading}>
            {(data?.samples ?? []).map((s, i) => (
              <li key={`${s.name}-${i}`} className="rounded-2xl bg-paper p-5 text-ink-900">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-display text-lg font-semibold" aria-label={h.liveHidden}>
                      {s.name}
                    </p>
                    {s.city ? <p className="text-sm text-mist-500">{s.city}</p> : null}
                  </div>
                  {s.score != null ? <ScoreBadge score={s.score} /> : null}
                </div>
                {s.reason ? (
                  <>
                    <p className="mt-3 text-xs font-semibold text-rasd-700">{t.site.mockup.whyTitle}</p>
                    <p className="mt-1 text-sm leading-relaxed">{s.reason}</p>
                  </>
                ) : null}
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {s.contact_types.map((k) => {
                    const Icon = CONTACT_ICONS[k] ?? Phone;
                    return (
                      <span key={k} className="inline-flex items-center gap-1 rounded-full bg-rasd-100 px-2.5 py-1 text-xs text-rasd-800">
                        <Icon className="size-3.5" aria-hidden />
                        {h.liveContacts[k as keyof typeof h.liveContacts] ?? k}
                        <span aria-hidden className="tracking-widest text-rasd-800/50">
                          ••••
                        </span>
                      </span>
                    );
                  })}
                </div>
              </li>
            ))}
            {preview.isLoading
              ? [0, 1, 2].map((i) => <li key={i} className="h-32 animate-pulse rounded-2xl bg-white/[0.06]" />)
              : null}
          </ul>
        </div>
      </div>
    </Section>
  );
}
