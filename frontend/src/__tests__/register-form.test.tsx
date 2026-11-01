import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RegisterForm, registerSchema } from "@/features/auth/register-form";
import { I18nProvider } from "@/i18n/provider";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

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

beforeEach(() => {
  window.localStorage.setItem("lh-locale", "en");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("register schema", () => {
  const ok = { full_name: "Sara", company: "Nile Dental", email: "s@n.eg", phone: "+20 100 123 4567", password: "long-enough-pw" };

  it("accepts a complete signup", () => {
    expect(registerSchema.safeParse(ok).success).toBe(true);
  });

  it.each([
    ["phone", "call me"],
    ["phone", "123"],
    ["password", "short"],
    ["email", "nope"],
    ["company", " "],
  ])("rejects a bad %s", (field, value) => {
    expect(registerSchema.safeParse({ ...ok, [field]: value }).success).toBe(false);
  });
});

describe("register form", () => {
  it("shows the trial terms from the server and reports a taken email", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/public/trial")) return json({ trial_days: 14, trial_credits: 50 });
      return json({ error: { code: "email_taken", message: "exists" } }, 409);
    });
    wrap(<RegisterForm />);
    expect(await screen.findByText("Free for 14 days with 50 points. No card needed.")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Your name"), "Sara Ahmed");
    await userEvent.type(screen.getByLabelText("Company"), "Nile Dental");
    await userEvent.type(screen.getByLabelText("Work email"), "sara@nile.eg");
    await userEvent.type(screen.getByLabelText("Phone / WhatsApp"), "+20 100 123 4567");
    await userEvent.type(screen.getByLabelText("Password (10+ characters)"), "long-enough-pw");
    await act(async () => {
      await userEvent.click(screen.getByRole("button", { name: "Start free trial" }));
    });
    expect(await screen.findByText("An account with this email already exists. Sign in instead.")).toBeInTheDocument();
    const call = fetchSpy.mock.calls.find(([u]) => String(u).endsWith("/auth/register"));
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ email: "sara@nile.eg", locale: "en" });
  });

  it("toggles password visibility, links the legal pages and says credits come after confirming", async () => {
    vi.spyOn(global, "fetch").mockImplementation(async () => json({ trial_days: 30, trial_credits: 100 }));
    wrap(<RegisterForm />);
    expect(await screen.findByText(/Your 100 free points are added once you confirm/)).toBeInTheDocument();
    const pw = screen.getByLabelText("Password (10+ characters)");
    expect(pw).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(pw).toHaveAttribute("type", "text");
    expect(screen.getByRole("link", { name: "Terms of use" })).toHaveAttribute("href", "/terms");
    expect(screen.getByRole("link", { name: "Privacy policy" })).toHaveAttribute("href", "/privacy");
  });
});
