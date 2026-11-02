import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BillingPage } from "@/features/billing/billing";
import { OutOfCredits } from "@/features/billing/out-of-credits";
import { I18nProvider } from "@/i18n/provider";

const search = { value: "" };
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/billing",
  useSearchParams: () => new URLSearchParams(search.value),
}));

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nProvider>
      <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
    </I18nProvider>,
  );
}

const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });

const summary = {
  billing_exempt: false,
  balance: 7,
  on_trial: true,
  trial_ends_at: "2026-11-20T10:00:00Z",
  trial_days_left: 21,
  trial_expired: false,
  credits_per_contact: 1,
  low_balance: true,
  pending_topups: 0,
  payment_instructions_ar: "حوّل على إنستاباي",
  payment_instructions_en: "Send via InstaPay to mathew@instapay",
  paypal_enabled: true,
};

function mockApi(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    "/auth/me": { user: { id: "u", email: "o@x.co", full_name: "O", is_active: true, locale: "en" }, workspace_id: "w", workspace_name: "W", role: "owner", csrf_token: null, demo_mode: false },
    "/billing/summary": summary,
    "/billing/packages": [{ id: "p1", name_ar: "باقة 500", name_en: "500 pack", credits: 500, price: "50.00", currency: "USD" }],
    "/billing/paypal/orders": { order_id: "ORD1", approve_url: "https://www.sandbox.paypal.com/checkoutnow?token=ORD1" },
    "/billing/paypal/capture": { id: "t2", package_id: "p1", credits: 500, amount: "50.00", currency: "USD", method: "paypal", reference: "ORD1", receipt_filename: null, status: "approved", reason: null, created_at: "2026-11-02T10:00:00Z", reviewed_at: "2026-11-02T10:01:00Z" },
    "/billing/topups": [{ id: "t1", package_id: "p1", credits: 500, amount: "750.00", currency: "EGP", method: "vodafone_cash", reference: null, receipt_filename: "r.png", status: "rejected", reason: "Amount did not match", created_at: "2026-10-30T10:00:00Z", reviewed_at: "2026-10-30T11:00:00Z" }],
    "/billing/transactions": { items: [{ id: "x1", delta: 100, balance_after: 100, kind: "trial_grant", campaign_id: null, business_id: null, note: "Free trial", created_at: "2026-10-30T09:00:00Z" }, { id: "x2", delta: -1, balance_after: 99, kind: "campaign_charge", campaign_id: "c", business_id: "b", note: null, created_at: "2026-10-30T09:30:00Z" }], total: 2, page: 1, page_size: 20 },
    ...overrides,
  };
  return vi.spyOn(global, "fetch").mockImplementation(async (input) => {
    const path = String(input).replace("/api/v1", "").split("?")[0];
    return json(routes[path]);
  });
}

beforeEach(() => {
  window.localStorage.setItem("lh-locale", "en");
  search.value = "";
  Element.prototype.scrollIntoView = vi.fn(); // jsdom has no layout
});
afterEach(() => vi.restoreAllMocks());

describe("billing page", () => {
  it("shows balance, trial, low-balance warning, requests and ledger", async () => {
    mockApi();
    wrap(<BillingPage />);
    expect(await screen.findByText("Free trial: 21 days left")).toBeInTheDocument();
    expect(screen.getByText("Low balance: top up so your campaigns don't stop.")).toBeInTheDocument();
    expect(await screen.findByText("Amount did not match")).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(await screen.findByText("Contact delivered")).toBeInTheDocument();
    expect(screen.getByText("+100")).toBeInTheDocument();
  });

  it("sells packages in dollars through PayPal checkout", async () => {
    const fetch = mockApi();
    wrap(<BillingPage />);
    expect(await screen.findByText("$50")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Pay with PayPal" }));
    const call = fetch.mock.calls.find(([url]) => String(url).includes("/billing/paypal/orders"));
    expect(call).toBeTruthy();
    expect(JSON.parse(String(call![1]?.body))).toEqual({ package_id: "p1" });
    expect(screen.queryByText("Send for review")).not.toBeInTheDocument(); // no manual transfers any more
  });

  it("captures the payment when the client comes back from PayPal", async () => {
    search.value = "paypal=return&token=ORD1";
    const fetch = mockApi();
    wrap(<BillingPage />);
    await screen.findByText("$50");
    await vi.waitFor(() => {
      const call = fetch.mock.calls.find(([url]) => String(url).includes("/billing/paypal/capture"));
      expect(JSON.parse(String(call![1]?.body))).toEqual({ order_id: "ORD1" });
    });
  });

  it("disables checkout until the store's PayPal account is connected", async () => {
    mockApi({ "/billing/summary": { ...summary, paypal_enabled: false } });
    wrap(<BillingPage />);
    expect(await screen.findByText("Online payment is not available right now. Please try again later.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Pay with PayPal" })).toBeDisabled();
  });

  it("tells unmetered workspaces they don't use credits", async () => {
    mockApi({ "/billing/summary": { ...summary, billing_exempt: true, low_balance: false } });
    wrap(<BillingPage />);
    expect(await screen.findByText("This workspace is not metered: campaigns don't use points.")).toBeInTheDocument();
    expect(screen.queryByText("Buy points")).not.toBeInTheDocument();
  });
});

describe("out-of-credits panel", () => {
  it("links to top-up when the balance is empty", async () => {
    mockApi({ "/billing/summary": { ...summary, balance: 0 } });
    wrap(<OutOfCredits />);
    expect(await screen.findByText("You're out of points")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Top up points" })).toHaveAttribute("href", "/app/billing");
  });

  it("explains an ended trial and a stopped search", async () => {
    mockApi({ "/billing/summary": { ...summary, trial_expired: true } });
    const { unmount } = wrap(<OutOfCredits />);
    expect(await screen.findByText("Your free trial has ended")).toBeInTheDocument();
    unmount();
    wrap(<OutOfCredits stopped />);
    expect(await screen.findByText("This search stopped: not enough points")).toBeInTheDocument();
  });

  it("stays silent with credits left, and warns on low balance only when asked", async () => {
    mockApi();
    const { container, unmount } = wrap(<OutOfCredits />);
    await new Promise((r) => setTimeout(r, 50));
    expect(container).toBeEmptyDOMElement();
    unmount();
    wrap(<OutOfCredits warnLow />);
    expect(await screen.findByText("Your balance is running low")).toBeInTheDocument();
  });
});
