"use client";

import { useQuery } from "@tanstack/react-query";
import { Quote, Star } from "lucide-react";

import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { PublicTestimonial } from "@/types/api";

import { Reveal } from "./motion";
import { Heading, Section } from "./parts";

export function Stars({ n, className }: { n: number; className?: string }) {
  const { t } = useI18n();
  return (
    <span className={cn("inline-flex gap-0.5", className)} role="img" aria-label={t.site.testimonials.rating.replace("{n}", String(n))}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Star key={i} className={cn("size-4", i <= n ? "fill-sun-500 text-sun-500" : "text-muted-foreground/30")} aria-hidden />
      ))}
    </span>
  );
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("");
}

/** Approved reviews from the admin. The whole section stays hidden until there is at least one. */
export function Testimonials() {
  const { t, locale } = useI18n();
  const h = t.site.home;
  const q = useQuery({
    queryKey: ["public-testimonials"],
    queryFn: () => api<PublicTestimonial[]>("/public/testimonials"),
    staleTime: 5 * 60_000,
  });
  const items = (q.data ?? []).filter((x) => (locale === "ar" ? x.body_ar || x.body_en : x.body_en || x.body_ar));
  if (!items.length) return null;
  return (
    <Section tone="muted">
      <Heading title={h.testimonialsTitle} subtitle={h.testimonialsSubtitle} />
      <div className="columns-1 gap-4 space-y-4 md:columns-2 lg:columns-3">
        {items.map((x, i) => {
          const body = locale === "ar" ? x.body_ar || x.body_en : x.body_en || x.body_ar;
          const meta = [x.author_role, x.company, x.city].filter(Boolean).join(" · ");
          return (
            <Reveal key={x.id} delay={(i % 3) * 80} className="break-inside-avoid">
              <figure className={cn("rounded-2xl border bg-card p-6", x.is_featured && "border-rasd-600/30 ring-1 ring-rasd-600/15")}>
                <div className="flex items-center justify-between">
                  <Stars n={x.rating} />
                  <Quote className="size-5 text-rasd-500/40" aria-hidden />
                </div>
                <blockquote className="mt-4 leading-relaxed text-foreground/90">{body}</blockquote>
                <figcaption className="mt-5 flex items-center gap-3">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-ink-900 font-display text-sm font-semibold text-signal-400">
                    {initials(x.author_name)}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold">{x.author_name}</span>
                    {meta ? <span className="block truncate text-xs text-muted-foreground">{meta}</span> : null}
                  </span>
                </figcaption>
              </figure>
            </Reveal>
          );
        })}
      </div>
    </Section>
  );
}
