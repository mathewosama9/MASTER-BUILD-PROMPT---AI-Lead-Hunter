"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Input } from "@/components/ui/primitives";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import type { CreditPackage } from "@/types/api";

import { Heading, Section } from "./parts";

const WEEKS_PER_MONTH = 52 / 12;

/**
 * "What does finding clients by hand cost you?" Every input is the visitor's own; the only number from us is the
 * real per-client price of the smallest package (the most expensive per point, so the comparison is fair).
 */
export function CostCalculator({ tone = "muted" }: { tone?: "plain" | "muted" }) {
  const { t, locale } = useI18n();
  const c = t.site.calc;
  const [hours, setHours] = useState("");
  const [rate, setRate] = useState("");
  const [leads, setLeads] = useState("");
  const pkgs = useQuery({ queryKey: ["public-packages"], queryFn: () => api<CreditPackage[]>("/public/packages"), staleTime: 0 });
  const smallest = [...(pkgs.data ?? [])].sort((a, b) => a.credits - b.credits)[0];
  const perLead = smallest ? Number(smallest.price) / smallest.credits : null;

  const h = Number(hours);
  const r = Number(rate);
  const n = Number(leads);
  const ready = h > 0 && r > 0 && n > 0;
  const monthHours = h * WEEKS_PER_MONTH;
  const manual = monthHours * r;
  const rasd = perLead != null ? n * perLead : null;
  const money = (v: number) => `${formatNumber(Math.round(v), locale)} ${smallest?.currency ?? ""}`.trim();

  const field = (id: string, label: string, value: string, set: (v: string) => void) => (
    <label htmlFor={id} className="block">
      <span className="text-sm font-medium">{label}</span>
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        min={0}
        placeholder={c.placeholder}
        value={value}
        onChange={(e) => set(e.target.value)}
        className="mt-1.5 h-11 text-base"
      />
    </label>
  );

  return (
    <Section tone={tone}>
      <Heading title={c.title} subtitle={c.subtitle} />
      <div className="mx-auto grid max-w-5xl gap-4 md:grid-cols-[1fr_1.1fr]">
        <div className="space-y-4 rounded-2xl border bg-card p-6">
          {field("calc-hours", c.hours, hours, setHours)}
          {field("calc-rate", smallest ? c.rate.replace("{currency}", smallest.currency) : c.rateNoCurrency, rate, setRate)}
          {field("calc-leads", c.leads, leads, setLeads)}
        </div>
        <div className="flex flex-col justify-center rounded-2xl bg-ink-900 p-6 text-paper" aria-live="polite">
          {ready ? (
            <dl className="space-y-5">
              <div>
                <dt className="text-sm text-mist-300">{c.manual}</dt>
                <dd className="mt-1 font-display text-4xl font-bold tabular-nums">{money(manual)}</dd>
                <dd className="mt-1 text-sm text-mist-300">
                  {c.manualHours.replace("{h}", formatNumber(Math.round(monthHours), locale))}
                </dd>
              </div>
              {rasd != null ? (
                <div className="border-t border-white/10 pt-5">
                  <dt className="text-sm text-mist-300">{c.rasd.replace("{n}", formatNumber(n, locale))}</dt>
                  <dd className="mt-1 font-display text-4xl font-bold tabular-nums text-signal-400">{money(rasd)}</dd>
                  <dd className="mt-1 text-sm text-mist-300">{c.rasdNote}</dd>
                </div>
              ) : null}
            </dl>
          ) : (
            <p className="text-center leading-relaxed text-mist-300">{c.empty}</p>
          )}
        </div>
      </div>
      <p className="mx-auto mt-4 max-w-3xl text-center text-xs text-muted-foreground">{c.disclaimer}</p>
    </Section>
  );
}
