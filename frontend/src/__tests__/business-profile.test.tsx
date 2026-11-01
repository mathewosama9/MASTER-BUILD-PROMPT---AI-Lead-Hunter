import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BusinessProfileTab } from "@/features/settings/business-profile";
import { I18nProvider } from "@/i18n/provider";

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nProvider>
      <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
    </I18nProvider>,
  );
}

const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });

const PROFILE = {
  company_name: "Codex",
  website: null,
  business_category: "medical_supplier",
  description: "",
  value_proposition: "",
  offerings: [{ id: "o_1", name: "Dental chairs", description: "", keywords: [] }],
  target_industries: [],
  target_countries: [],
  target_cities: [],
  company_sizes: [],
  good_signals: [],
  disqualifiers: [],
  channels: [],
  sender_name: "",
  outreach_language: "ar",
  tone: "professional",
  onboarding: { step: 0, completed: false, steps: 6 },
};
const META = {
  demo_mode: false,
  countries: [],
  industries: [{ key: "dental_clinics", en: "Dental Clinics", ar: "عيادات الأسنان" }],
  services: [],
  scoring: { weights: {}, thresholds: {}, version: "1" },
  provider_categories: [
    {
      key: "medical_supplier",
      en: "Medical supplies",
      ar: "توريدات طبية",
      offerings: [{ en: "Consumables", ar: "مستهلكات" }],
      targets: ["dental_clinics"],
    },
  ],
};

beforeEach(() => window.localStorage.setItem("lh-locale", "en"));
afterEach(() => vi.restoreAllMocks());

describe("my business tab", () => {
  it("suggests services for the category and saves offerings with the ideal customer", async () => {
    const spy = vi.spyOn(global, "fetch").mockImplementation(async (url, init) => {
      const u = String(url);
      if (u.endsWith("/meta")) return json(META);
      if (u.endsWith("/profile") && (init as RequestInit | undefined)?.method === "PUT") {
        return json({ ...PROFILE, ...JSON.parse(String((init as RequestInit).body)) });
      }
      return json(PROFILE);
    });
    wrap(<BusinessProfileTab canEdit />);
    expect(await screen.findByDisplayValue("Dental chairs")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: /Suggest services for my category/ }));
    expect(screen.getByDisplayValue("Consumables")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Dental Clinics/ })).toBeInTheDocument(); // category targets added
    await userEvent.type(screen.getByLabelText("Cities / governorates"), "Riyadh, المنوفية");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const put = spy.mock.calls.find(([u, i]) => String(u).endsWith("/profile") && (i as RequestInit)?.method === "PUT");
    const body = JSON.parse(String((put![1] as RequestInit).body));
    expect(body.offerings.map((o: { name: string }) => o.name)).toEqual(["Dental chairs", "Consumables"]);
    expect(body.offerings[0].id).toBe("o_1");
    expect(body.target_industries).toEqual(["dental_clinics"]);
    expect(body.target_cities).toEqual(["Riyadh", "المنوفية"]);
  });

  it("is read-only for non-admins", async () => {
    vi.spyOn(global, "fetch").mockImplementation(async (url) => json(String(url).endsWith("/meta") ? META : PROFILE));
    wrap(<BusinessProfileTab canEdit={false} />);
    expect(await screen.findByDisplayValue("Dental chairs")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });
});
