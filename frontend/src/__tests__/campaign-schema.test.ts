import { describe, expect, it } from "vitest";

import { campaignSchema, defaultCampaignValues, toApiPayload } from "@/features/campaigns/schema";

const valid = {
  ...defaultCampaignValues,
  name: "Riyadh dental",
  industry: "dental_clinics",
  sources: ["demo"],
  keywords: "orthodontics, تقويم، implants",
};

describe("campaign form validation", () => {
  it("accepts a complete demo campaign and splits Arabic/English keywords", () => {
    const r = campaignSchema.safeParse(valid);
    expect(r.success).toBe(true);
    if (r.success) expect(r.data.keywords).toEqual(["orthodontics", "تقويم", "implants"]);
  });

  it("requires at least one source", () => {
    const r = campaignSchema.safeParse({ ...valid, sources: [] });
    expect(r.success).toBe(false);
    expect(r.error?.issues.some((i) => i.path[0] === "sources")).toBe(true);
  });

  it("rejects mixing demo fixtures with real providers", () => {
    const r = campaignSchema.safeParse({ ...valid, sources: ["demo", "brave"] });
    expect(r.success).toBe(false);
  });

  it("requires max companies >= target", () => {
    const r = campaignSchema.safeParse({ ...valid, target_count: 50, max_companies: 10 });
    expect(r.success).toBe(false);
    expect(r.error?.issues[0].path).toEqual(["max_companies"]);
  });

  it("requires URLs for manual/facebook sources", () => {
    expect(campaignSchema.safeParse({ ...valid, sources: ["facebook"] }).success).toBe(false);
    expect(campaignSchema.safeParse({ ...valid, sources: ["facebook"], manual_urls: "https://a.sa|https://facebook.com/a" }).success).toBe(true);
  });

  it("requires validated rows for the file import source and sends them as the source rows", () => {
    expect(campaignSchema.safeParse({ ...valid, sources: ["import"] }).success).toBe(false);
    const row = JSON.stringify({ name: "Acme", website: "https://acme.sa" });
    const r = campaignSchema.safeParse({ ...valid, sources: ["import", "osm"], import_rows: [row] });
    expect(r.success).toBe(true);
    const payload = toApiPayload(r.data!, false);
    expect(payload.sources).toEqual([
      { provider_key: "import", manual_urls: [row] },
      { provider_key: "osm", manual_urls: [] },
    ]);
  });

  it("rejects invalid country codes and numbers out of range", () => {
    expect(campaignSchema.safeParse({ ...valid, country: "Saudi" }).success).toBe(false);
    expect(campaignSchema.safeParse({ ...valid, min_score: 150 }).success).toBe(false);
    expect(campaignSchema.safeParse({ ...valid, concurrency: 0 }).success).toBe(false);
  });

  it("builds the API payload expected by the backend", () => {
    const parsed = campaignSchema.parse({ ...valid, sources: ["manual"], manual_urls: "https://a.sa\n\nhttps://b.sa" });
    const body = toApiPayload(parsed, true);
    expect(body.start).toBe(true);
    expect(body.sources).toEqual([{ provider_key: "manual", manual_urls: ["https://a.sa", "https://b.sa"] }]);
    expect(body.settings.target_count).toBe(20);
    expect(body.city).toBeNull();
  });
});
