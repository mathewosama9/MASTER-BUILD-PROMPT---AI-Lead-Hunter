import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPage } from "@/features/admin/admin";
import { I18nProvider } from "@/i18n/provider";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/app/admin" }));

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nProvider>
      <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
    </I18nProvider>,
  );
}

const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
const me = (superuser: boolean) => ({
  user: { id: "u", email: "m@codex.eg", full_name: "M", is_active: true, is_superuser: superuser, locale: "en" },
  workspace_id: "w",
  workspace_name: "W",
  role: "owner",
  csrf_token: null,
  demo_mode: false,
});
const topup = {
  id: "t1",
  package_id: "p",
  credits: 500,
  amount: "750.00",
  currency: "EGP",
  method: "instapay",
  reference: "IPN-1",
  receipt_filename: "r.png",
  status: "pending",
  reason: null,
  created_at: "2026-10-31T09:00:00Z",
  reviewed_at: null,
  workspace_id: "w2",
  workspace_name: "Nile Dental",
  requested_by: "sara@nile.eg",
};

  const overview = {
    users: { last_7d: 2, last_30d: 5, total: 9 },
    workspaces: { total: 7, active_30d: 3 },
    revenue: { last_30d: [{ currency: "EGP", amount: 1500 }], total: [{ currency: "EGP", amount: 4000 }], monthly: [] },
    credits_used_30d: 120,
    attention: { pending_topups: 1, new_contacts: 0, pending_reviews: 2, sample_reviews: 6 },
    funnel: { signed_up: 7, verified: 5, first_search: 4, paid: 2 },
    daily: [{ date: "2026-11-01", signups: 1, credits_used: 10 }],
  };

beforeEach(() => window.localStorage.setItem("lh-locale", "en"));
afterEach(() => vi.restoreAllMocks());

describe("admin page", () => {
  it("lists pending top-ups and approves one", async () => {
    const spy = vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/auth/me")) return json(me(true));
      if (url.includes("/approve") && init?.method === "POST") return json({ ...topup, status: "approved" });
      if (url.includes("/admin/topups")) return json([topup]);
      if (url.includes("/admin/overview")) return json(overview);
      return json([]);
    });
    wrap(<AdminPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Top-up requests" }));
    expect(await screen.findByText("Nile Dental")).toBeInTheDocument();
    expect(screen.getByText("sara@nile.eg")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View/ })).toHaveAttribute("href", "/api/v1/admin/topups/t1/receipt");
    await act(async () => {
      await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    });
    expect(spy.mock.calls.some(([u, i]) => String(u).endsWith("/admin/topups/t1/approve") && i?.method === "POST")).toBe(true);
  });

  it("rejecting needs a reason", async () => {
    vi.spyOn(global, "fetch").mockImplementation(async (input) =>
      String(input).includes("/auth/me")
        ? json(me(true))
        : String(input).includes("/admin/topups")
          ? json([topup])
          : String(input).includes("/admin/overview")
            ? json(overview)
            : json([]),
    );
    wrap(<AdminPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Top-up requests" }));
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Reject" });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Reason"), "Amount does not match");
    expect(confirm).toBeEnabled();
  });

  it("opens on the overview and warns while sample reviews are live", async () => {
    vi.spyOn(global, "fetch").mockImplementation(async (input) =>
      String(input).includes("/auth/me") ? json(me(true)) : String(input).includes("/admin/overview") ? json(overview) : json([]),
    );
    wrap(<AdminPage />);
    expect(await screen.findByText(/6 sample reviews are live on the website/)).toBeInTheDocument();
    expect(screen.getByText("1,500 EGP")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1 top-up requests waiting" })).toBeInTheDocument();
    expect(screen.getByText(/4. Paid/)).toBeInTheDocument();
  });

  it("is closed to non-admins", async () => {
    vi.spyOn(global, "fetch").mockImplementation(async () => json(me(false)));
    wrap(<AdminPage />);
    expect(await screen.findByText("This page is for platform admins only.")).toBeInTheDocument();
  });
});
