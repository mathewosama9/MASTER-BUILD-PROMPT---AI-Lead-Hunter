import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { dictionaries } from "@/i18n/dictionaries";
import { I18nProvider } from "@/i18n/provider";
import { ContactPage } from "@/features/site/contact";
import { HomePage } from "@/features/site/home";
import { PricingPage } from "@/features/site/pricing";
import { HowItWorksPage } from "@/features/site/how-it-works";
import { UseCasesPage } from "@/features/site/use-cases";
import { siteAr, siteEn } from "@/i18n/site";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/" }));

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

function mockApi(routes: Record<string, unknown>) {
  return vi.spyOn(global, "fetch").mockImplementation(async (input) => {
    const path = String(input).replace("/api/v1", "").split("?")[0];
    return path in routes ? json(routes[path]) : json({ error: { message: "nope" } }, 404);
  });
}

const trial = { trial_days: 30, trial_credits: 100, credits_per_contact: 1 };

beforeEach(() => window.localStorage.setItem("lh-locale", "en"));
afterEach(() => vi.restoreAllMocks());

describe("public site", () => {
  it("home shows the trial terms from the server and every before/after pair", async () => {
    mockApi({ "/public/trial": { ...trial, trial_days: 14, trial_credits: 40 } });
    wrap(<HomePage />);
    expect((await screen.findAllByText("14 days free · 40 points · no card needed")).length).toBeGreaterThan(0);
    for (const pair of dictionaries.en.site.home.pairs) {
      expect(screen.getByText(pair.before)).toBeInTheDocument();
      expect(screen.getByText(pair.after)).toBeInTheDocument();
    }
  });

  it("home renders in Arabic by default", async () => {
    window.localStorage.removeItem("lh-locale");
    mockApi({ "/public/trial": trial });
    wrap(<HomePage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(dictionaries.ar.site.home.title);
  });

  it("use-cases page shows a block per type of business with a sample message", () => {
    mockApi({ "/public/trial": trial });
    wrap(<UseCasesPage />);
    for (const item of dictionaries.en.site.useCases.items) {
      expect(screen.getByRole("heading", { name: item.title })).toBeInTheDocument();
      expect(screen.getByText(item.message)).toBeInTheDocument();
    }
  });

  it("how-it-works page lists every stage", () => {
    mockApi({ "/public/trial": trial });
    wrap(<HowItWorksPage />);
    for (const stage of dictionaries.en.site.how.stages) {
      expect(screen.getByRole("heading", { name: stage.title })).toBeInTheDocument();
    }
  });

  it("home shows approved testimonials and hides the section when there are none", async () => {
    mockApi({
      "/public/trial": trial,
      "/public/testimonials": [
        {
          id: "t1",
          author_name: "Sara K.",
          author_role: "Founder",
          company: null,
          city: "Riyadh",
          country: "SA",
          rating: 5,
          body_ar: "ممتاز",
          body_en: "We found our first ten clients in a week.",
          is_featured: true,
        },
      ],
    });
    wrap(<HomePage />);
    expect(await screen.findByText("We found our first ten clients in a week.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: dictionaries.en.site.home.testimonialsTitle })).toBeInTheDocument();
  });

  it("marketing copy never names data providers or the old brand", () => {
    // Legal pages are excluded: the OpenStreetMap licence requires its attribution in the terms.
    const text = JSON.stringify([siteEn, siteAr].map((x) => ({ ...x, legal: undefined })));
    for (const word of ["Google", "جوجل", "OpenStreetMap", "Brave", "Hunter", "Apollo", "Lusha", "DeepSeek", "CODEX"]) {
      expect(text).not.toContain(word);
    }
  });

  it("pricing lists the packages the admin configured", async () => {
    mockApi({
      "/public/trial": trial,
      "/public/packages": [{ id: "p", name_ar: "أساسية", name_en: "Starter", credits: 250, price: "400.00", currency: "EGP" }],
    });
    wrap(<PricingPage />);
    expect(await screen.findByText("Starter")).toBeInTheDocument();
    expect(screen.getByText(/250 points · ≈ 1\.6 EGP per client/)).toBeInTheDocument();
    expect(await screen.findByText("30 days with 100 points to run real searches. No card needed.")).toBeInTheDocument();
  });

  it("pricing without packages points to the contact page", async () => {
    mockApi({ "/public/trial": trial, "/public/packages": [] });
    wrap(<PricingPage />);
    expect(await screen.findByText(/Packages are being finalised/)).toBeInTheDocument();
  });

  it("contact form validates, sends, and confirms", async () => {
    const fetchSpy = mockApi({ "/public/contact": { status: "received" } });
    wrap(<ContactPage />);
    await act(async () => {
      await userEvent.click(screen.getByRole("button", { name: "Send" }));
    });
    expect(fetchSpy).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Your name"), "Omar");
    await userEvent.type(screen.getByLabelText("Email"), "omar@clinic.sa");
    await userEvent.selectOptions(screen.getByLabelText("What can we help with?"), "sales");
    await act(async () => {
      await userEvent.click(screen.getByRole("button", { name: "Send" }));
    });
    expect(await screen.findByText("Thank you, we've received your message.")).toBeInTheDocument();
    const body = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body));
    expect(body).toMatchObject({ name: "Omar", email: "omar@clinic.sa", interest: "sales", locale: "en" });
  });
});
