import { describe, expect, it } from "vitest";

import { campaignSchema, defaultCampaignValues, toApiPayload } from "@/features/campaigns/schema";

const valid = {
  ...defaultCampaignValues,
  name: "Riyadh dental",
  industry: "dental_clinics",
  keywords: "orthodontics, تقويم، implants",
};

describe("campaign form validation", () => {
  it("accepts a complete campaign and splits Arabic/English keywords", () => {
    const r = campaignSchema.safeParse(valid);
    expect(r.success).toBe(true);
    if (r.success) expect(r.data.keywords).toEqual(["orthodontics", "تقويم", "implants"]);
  });

  it("rejects invalid country codes and lead counts out of range", () => {
    expect(campaignSchema.safeParse({ ...valid, country: "Saudi" }).success).toBe(false);
    expect(campaignSchema.safeParse({ ...valid, target_count: 0 }).success).toBe(false);
    expect(campaignSchema.safeParse({ ...valid, target_count: 501 }).success).toBe(false);
  });

  it("sends only what the user chose: sources and research settings are the platform admin's", () => {
    const parsed = campaignSchema.parse({ ...valid, target_count: "35" });
    const body = toApiPayload(parsed, true);
    expect(body.start).toBe(true);
    expect(body).not.toHaveProperty("sources");
    expect(body.settings).toEqual({ target_count: 35 });
    expect(body.city).toBeNull();
  });
});
