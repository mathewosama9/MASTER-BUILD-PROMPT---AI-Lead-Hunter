import { z } from "zod";

// Error messages are keys into the `validation` dictionary; the UI translates them.

const list = z
  .string()
  .optional()
  .transform((v) =>
    (v ?? "")
      .split(/[,،\n]/)
      .map((s) => s.trim())
      .filter(Boolean),
  );

export const campaignSchema = z
  .object({
    name: z.string().trim().min(1, "nameRequired").max(200),
    country: z.string().regex(/^[A-Z]{2}$/, "chooseCountry"),
    city: z.string().max(120).optional(),
    region: z.string().max(120).optional(),
    language: z.enum(["en", "ar"]),
    industry: z.string().trim().min(2, "chooseIndustry").max(120),
    keywords: list,
    excluded_keywords: list,
    company_size: z.string().optional(),
    characteristics: list,
    services: z.array(z.string()).max(10),
    nl_query: z.string().max(2000).optional(),
    sources: z.array(z.string()).min(1, "selectSource"),
    manual_urls: z.string().optional(),
    // Validated rows from POST /campaigns/import-preview (JSON strings), used by the "import" source.
    import_rows: z.array(z.string()).optional(),
    target_count: z.coerce.number().int().min(1).max(500),
    max_companies: z.coerce.number().int().min(1).max(1000),
    max_pages_per_site: z.coerce.number().int().min(1).max(15),
    enrichment: z.boolean(),
    ai_analysis: z.boolean(),
    email_verification: z.boolean(),
    min_score: z.coerce.number().min(0).max(100),
    max_budget_usd: z.coerce.number().min(0).max(1000),
    max_runtime_minutes: z.coerce.number().int().min(1).max(600),
    concurrency: z.coerce.number().int().min(1).max(10),
    exclude_duplicates: z.boolean(),
  })
  .refine((v) => v.max_companies >= v.target_count, {
    path: ["max_companies"],
    message: "maxCompaniesMin",
  })
  .refine((v) => !(v.sources.includes("demo") && v.sources.length > 1), {
    path: ["sources"],
    message: "demoMix",
  })
  .refine(
    (v) => !v.sources.some((s) => s === "facebook" || s === "manual") || (v.manual_urls ?? "").trim().length > 0,
    { path: ["manual_urls"], message: "manualUrlsRequired" },
  )
  .refine((v) => !v.sources.includes("import") || (v.import_rows ?? []).length > 0, {
    path: ["import_rows"],
    message: "importRequired",
  });

export type CampaignFormInput = z.input<typeof campaignSchema>;
export type CampaignFormValues = z.output<typeof campaignSchema>;

export const STEP_FIELDS: (keyof CampaignFormInput)[][] = [
  ["country", "city", "region", "language"],
  ["industry", "keywords", "excluded_keywords", "company_size", "characteristics", "services", "nl_query"],
  ["sources", "manual_urls", "import_rows"],
  [
    "target_count",
    "max_companies",
    "max_pages_per_site",
    "enrichment",
    "ai_analysis",
    "email_verification",
    "min_score",
    "max_budget_usd",
    "max_runtime_minutes",
    "concurrency",
    "exclude_duplicates",
  ],
  ["name"],
];

export const defaultCampaignValues: CampaignFormInput = {
  name: "",
  country: "SA",
  city: "",
  region: "",
  language: "en",
  industry: "",
  keywords: "",
  excluded_keywords: "",
  company_size: "",
  characteristics: "",
  services: [],
  nl_query: "",
  sources: [],
  manual_urls: "",
  import_rows: [],
  target_count: 20,
  max_companies: 40,
  max_pages_per_site: 5,
  enrichment: true,
  ai_analysis: true,
  email_verification: false,
  min_score: 50,
  max_budget_usd: 5,
  max_runtime_minutes: 30,
  concurrency: 4,
  exclude_duplicates: false,
};

export function toApiPayload(v: CampaignFormValues, start: boolean) {
  const urls = (v.manual_urls ?? "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  return {
    name: v.name,
    country: v.country,
    city: v.city || null,
    region: v.region || null,
    language: v.language,
    industry: v.industry,
    keywords: v.keywords,
    excluded_keywords: v.excluded_keywords,
    company_size: v.company_size || null,
    characteristics: v.characteristics,
    services: v.services,
    nl_query: v.nl_query || null,
    sources: v.sources.map((key) => ({
      provider_key: key,
      manual_urls: key === "import" ? (v.import_rows ?? []) : key === "facebook" || key === "manual" ? urls : [],
    })),
    settings: {
      target_count: v.target_count,
      max_companies: v.max_companies,
      max_pages_per_site: v.max_pages_per_site,
      enrichment: v.enrichment,
      ai_analysis: v.ai_analysis,
      email_verification: v.email_verification,
      min_score: v.min_score,
      max_budget_usd: v.max_budget_usd,
      max_runtime_minutes: v.max_runtime_minutes,
      concurrency: v.concurrency,
      exclude_duplicates: v.exclude_duplicates,
    },
    start,
  };
}
