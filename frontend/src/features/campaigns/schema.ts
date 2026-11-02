import { z } from "zod";

// Error messages are keys into the `validation` dictionary; the UI translates them.
// The user only says what they want (place, targeting, services, how many leads). Sources and every research
// setting are the platform admin's (Admin → Settings) and are applied by the server to every campaign.

const list = z
  .string()
  .optional()
  .transform((v) =>
    (v ?? "")
      .split(/[,،\n]/)
      .map((s) => s.trim())
      .filter(Boolean),
  );

export const campaignSchema = z.object({
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
  target_count: z.coerce.number().int().min(1).max(500),
});

export type CampaignFormInput = z.input<typeof campaignSchema>;
export type CampaignFormValues = z.output<typeof campaignSchema>;

export const STEP_FIELDS: (keyof CampaignFormInput)[][] = [
  ["country", "city", "region", "language"],
  [
    "industry",
    "keywords",
    "excluded_keywords",
    "company_size",
    "characteristics",
    "services",
    "nl_query",
    "target_count",
  ],
  ["name"],
];

export const defaultCampaignValues: CampaignFormInput = {
  name: "",
  country: "EG",
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
  target_count: 20,
};

export function toApiPayload(v: CampaignFormValues, start: boolean) {
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
    settings: { target_count: v.target_count },
    start,
  };
}
