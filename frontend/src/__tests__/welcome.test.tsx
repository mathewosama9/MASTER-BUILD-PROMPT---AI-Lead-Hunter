import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Welcome } from "@/features/onboarding/welcome";
import { I18nProvider } from "@/i18n/provider";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams("category=marketing_agency"),
}));

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nProvider>
      <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
    </I18nProvider>,
  );
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const PROFILE = {
  company_name: "",
  website: null,
  business_category: null,
  description: "",
  value_proposition: "",
  offerings: [],
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
  countries: [{ code: "AE", name_en: "UAE", name_ar: "الإمارات", cities: [{ en: "Dubai", ar: "دبي" }] }],
  industries: [
    { key: "cafes", en: "Cafés", ar: "المقاهي" },
    { key: "restaurants", en: "Restaurants", ar: "المطاعم" },
  ],
  services: [],
  scoring: { weights: {}, thresholds: {}, version: "1" },
  provider_categories: [
    {
      key: "marketing_agency",
      en: "Marketing agency",
      ar: "وكالة تسويق",
      offerings: [{ en: "Social media", ar: "سوشيال ميديا" }],
      targets: ["cafes", "restaurants"],
    },
  ],
};

beforeEach(() => {
  window.localStorage.setItem("lh-locale", "en");
  replace.mockReset();
});
afterEach(() => vi.restoreAllMocks());

function mockApi(firstSearch: () => Response) {
  let profile = { ...PROFILE };
  return vi.spyOn(global, "fetch").mockImplementation(async (url, init) => {
    const u = String(url);
    const method = (init as RequestInit | undefined)?.method;
    if (u.endsWith("/meta")) return json(META);
    if (u.endsWith("/profile/first-search")) return firstSearch();
    if (u.endsWith("/profile") && method === "PUT") {
      const body = JSON.parse(String((init as RequestInit).body));
      profile = { ...profile, ...body, offerings: (body.offerings ?? profile.offerings).map((o: object, i: number) => ({ id: `o_${i}`, ...o })) };
      return json(profile);
    }
    return json(profile);
  });
}

const bodies = (spy: ReturnType<typeof mockApi>) =>
  spy.mock.calls
    .filter(([u, i]) => String(u).endsWith("/profile") && (i as RequestInit)?.method === "PUT")
    .map(([, i]) => JSON.parse(String((i as RequestInit).body)));

describe("onboarding", () => {
  it("prefills from the site's category, saves each step and runs the first search", async () => {
    const spy = mockApi(() => json({ id: "c1" }, 201));
    wrap(<Welcome />);
    expect(await screen.findByRole("button", { name: "Marketing agency" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Social media")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Who do you sell to, and where?")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("City"), "Dubai");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText(/look for Cafés in Dubai, UAE/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Run my first search/ }));
    await vi.waitFor(() => expect(replace).toHaveBeenCalledWith("/app/campaigns/c1"));
    const [first, second] = bodies(spy);
    expect(first).toMatchObject({ business_category: "marketing_agency", onboarding_step: 1 });
    expect(first.offerings.map((o: { name: string }) => o.name)).toEqual(["Social media"]);
    expect(second).toMatchObject({
      target_industries: ["cafes", "restaurants"],
      target_countries: ["AE"],
      target_cities: ["Dubai"],
      onboarding_step: 2,
    });
  });

  it("asks to confirm the email when the trial points aren't active yet", async () => {
    mockApi(() => json({ error: { code: "email_unverified", message: "Confirm your email" } }, 403));
    wrap(<Welcome />);
    await userEvent.click(await screen.findByRole("button", { name: "Next" }));
    await userEvent.click(await screen.findByRole("button", { name: "Next" }));
    await userEvent.click(await screen.findByRole("button", { name: /Run my first search/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Confirm your email first/);
    expect(replace).not.toHaveBeenCalled();
  });
});
