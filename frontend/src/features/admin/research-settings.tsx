"use client";

import { ProviderStatusBadge } from "@/components/badges";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Checkbox, Field, Input, Switch } from "@/components/ui/primitives";
import { LoadingState } from "@/components/ui/states";
import { useProviders } from "@/hooks/queries";
import { useI18n } from "@/i18n/provider";
import { cn } from "@/lib/utils";

/** Platform-wide research settings (backend schemas/campaign.py ResearchDefaults), applied to every client campaign. */
export interface ResearchDefaults {
  sources: string[];
  concurrency: number;
  enrichment: boolean;
  ai_analysis: boolean;
  email_verification: boolean;
  exclude_duplicates: boolean;
  max_pages_per_site: number;
  min_score: number;
  companies_per_target: number;
  max_budget_usd: number;
  max_runtime_minutes: number | null;
}

// User-supplied lists and fixtures are not searchable sources.
const NOT_SEARCH = new Set(["demo", "manual", "facebook", "import"]);
const SOURCE_ORDER = ["google_maps", "osm", "directories", "social_discovery", "brave", "hunter", "x"];

type NumberKey = "concurrency" | "max_pages_per_site" | "min_score" | "companies_per_target" | "max_budget_usd";
const LIMITS: Record<NumberKey, [number, number]> = {
  concurrency: [1, 10],
  max_pages_per_site: [1, 15],
  min_score: [0, 100],
  companies_per_target: [1, 5],
  max_budget_usd: [0, 1000],
};

export function researchDefaultsValid(v: ResearchDefaults): boolean {
  const inRange = (Object.keys(LIMITS) as NumberKey[]).every((k) => {
    const [lo, hi] = LIMITS[k];
    return Number.isFinite(v[k]) && v[k] >= lo && v[k] <= hi;
  });
  const runtime = v.max_runtime_minutes === null || (Number.isInteger(v.max_runtime_minutes) && v.max_runtime_minutes >= 1 && v.max_runtime_minutes <= 1440);
  return inRange && runtime && v.sources.length > 0;
}

export function ResearchDefaultsEditor({ value, onChange }: { value: ResearchDefaults; onChange: (v: ResearchDefaults) => void }) {
  const { t } = useI18n();
  const r = t.admin.research;
  const providers = useProviders();
  const list = (providers.data ?? [])
    .filter((p) => p.kind === "discovery" && !NOT_SEARCH.has(p.key))
    .sort((a, b) => SOURCE_ORDER.indexOf(a.key) - SOURCE_ORDER.indexOf(b.key));
  const set = <K extends keyof ResearchDefaults>(k: K, v: ResearchDefaults[K]) => onChange({ ...value, [k]: v });
  const toggle = (key: string) =>
    set("sources", value.sources.includes(key) ? value.sources.filter((k) => k !== key) : [...value.sources, key]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{r.title}</CardTitle>
        <CardDescription>{r.hint}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <fieldset>
          <legend className="mb-2 text-xs font-medium">{r.sources}</legend>
          {providers.isLoading ? (
            <LoadingState rows={2} />
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {list.map((p) => {
                const on = value.sources.includes(p.key);
                return (
                  <label key={p.key} className={cn("flex cursor-pointer items-center gap-3 rounded-lg border p-3", on && "border-rasd-500 bg-rasd-500/10")}>
                    <Checkbox checked={on} onCheckedChange={() => toggle(p.key)} aria-label={p.name} />
                    <span className="flex-1 text-sm">{t.labels[p.key] ?? p.name}</span>
                    <ProviderStatusBadge status={p.status} />
                  </label>
                );
              })}
            </div>
          )}
          <p className={cn("mt-2 text-xs", value.sources.length ? "text-muted-foreground" : "text-destructive")}>
            {value.sources.length ? r.sourcesHint : r.sourcesRequired}
          </p>
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-3">
          {(
            [
              ["concurrency", t.wizard.concurrency],
              ["companies_per_target", r.companiesPerTarget],
              ["max_pages_per_site", t.wizard.maxPages],
              ["min_score", t.wizard.minScore],
              ["max_budget_usd", r.budget],
            ] as const
          ).map(([k, label]) => (
            <Field key={k} label={label} htmlFor={`rd_${k}`}>
              <Input
                id={`rd_${k}`}
                dir="ltr"
                type="number"
                min={LIMITS[k][0]}
                max={LIMITS[k][1]}
                value={Number.isFinite(value[k]) ? value[k] : ""}
                onChange={(e) => set(k, e.target.value === "" ? NaN : Number(e.target.value))}
              />
            </Field>
          ))}
          <Field label={r.runtime} htmlFor="rd_runtime" hint={r.runtimeHint}>
            <Input
              id="rd_runtime"
              dir="ltr"
              type="number"
              min={1}
              max={1440}
              placeholder={r.unlimited}
              value={value.max_runtime_minutes ?? ""}
              onChange={(e) => set("max_runtime_minutes", e.target.value === "" ? null : Number(e.target.value))}
            />
          </Field>
        </div>

        <div className="space-y-2">
          {(
            [
              ["enrichment", t.wizard.enrichment],
              ["ai_analysis", t.wizard.ai],
              ["email_verification", t.wizard.emailVerification],
              ["exclude_duplicates", t.wizard.excludeDuplicates],
            ] as const
          ).map(([k, label]) => (
            <div key={k} className="flex items-center justify-between gap-4 rounded-md border p-3">
              <label htmlFor={`rd_${k}`} className="text-sm">{label}</label>
              <Switch id={`rd_${k}`} checked={value[k]} onCheckedChange={(v) => set(k, v)} />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
