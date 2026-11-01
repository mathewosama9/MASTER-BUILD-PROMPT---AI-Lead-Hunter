import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ForgotPasswordForm, ResetPasswordForm, VerifyEmail, VerifyEmailBanner } from "@/features/auth/account-forms";
import { I18nProvider } from "@/i18n/provider";

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
const error = (status: number, code: string) => json({ error: { code, message: code } }, status);
const bodyOf = (spy: { mock: { calls: unknown[][] } }, path: string) => {
  const call = spy.mock.calls.find(([u]) => String(u).endsWith(path));
  return call ? JSON.parse(String((call[1] as RequestInit).body)) : undefined;
};

beforeEach(() => window.localStorage.setItem("lh-locale", "en"));
afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("forgot password", () => {
  it("sends the email and shows the same answer either way", async () => {
    const spy = vi.spyOn(global, "fetch").mockResolvedValue(json({ message: "ok" }, 202));
    wrap(<ForgotPasswordForm />);
    await userEvent.type(screen.getByLabelText("Email"), "sara@nile.eg");
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByText(/a reset link is on its way/)).toBeInTheDocument();
    expect(bodyOf(spy, "/auth/password/forgot")).toEqual({ email: "sara@nile.eg" });
  });
});

describe("reset password", () => {
  it("reads the token from the link, hides it, and saves the new password", async () => {
    window.history.replaceState(null, "", "/reset-password?token=tok-123");
    const spy = vi.spyOn(global, "fetch").mockResolvedValue(json({ message: "ok" }));
    wrap(<ResetPasswordForm />);
    expect(window.location.search).toBe("");
    await userEvent.type(screen.getByLabelText("New password (10+ characters)"), "a-brand-new-password");
    await userEvent.type(screen.getByLabelText("Confirm the new password"), "something-else-entirely");
    await userEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect(await screen.findByText("The passwords don't match")).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();

    await userEvent.clear(screen.getByLabelText("Confirm the new password"));
    await userEvent.type(screen.getByLabelText("Confirm the new password"), "a-brand-new-password");
    await userEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect(await screen.findByText(/Your password has been changed/)).toBeInTheDocument();
    expect(bodyOf(spy, "/auth/password/reset")).toEqual({ token: "tok-123", password: "a-brand-new-password" });
  });

  it("offers a new link when the token is rejected", async () => {
    window.history.replaceState(null, "", "/reset-password?token=old");
    vi.spyOn(global, "fetch").mockResolvedValue(error(400, "invalid_token"));
    wrap(<ResetPasswordForm />);
    await userEvent.type(screen.getByLabelText("New password (10+ characters)"), "a-brand-new-password");
    await userEvent.type(screen.getByLabelText("Confirm the new password"), "a-brand-new-password");
    await userEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect(await screen.findByRole("link", { name: "Request a new link" })).toHaveAttribute("href", "/forgot-password");
  });

  it("says the link is invalid when it has no token", async () => {
    wrap(<ResetPasswordForm />);
    expect(await screen.findByText(/invalid, already used or expired/)).toBeInTheDocument();
  });
});

describe("verify email", () => {
  it("confirms once with the token from the link", async () => {
    window.history.replaceState(null, "", "/verify-email?token=v-1");
    const spy = vi.spyOn(global, "fetch").mockResolvedValue(json({ message: "ok" }));
    wrap(<VerifyEmail />);
    expect(await screen.findByText(/Your email is confirmed/)).toBeInTheDocument();
    expect(spy.mock.calls.filter(([u]) => String(u).endsWith("/auth/email/verify"))).toHaveLength(1);
    expect(bodyOf(spy, "/auth/email/verify")).toEqual({ token: "v-1" });
  });

  it("explains an expired link", async () => {
    window.history.replaceState(null, "", "/verify-email?token=v-2");
    vi.spyOn(global, "fetch").mockResolvedValue(error(400, "invalid_token"));
    wrap(<VerifyEmail />);
    expect(await screen.findByText(/invalid or has expired/)).toBeInTheDocument();
  });
});

describe("confirmation banner", () => {
  it("mentions the trial and resends the email", async () => {
    const spy = vi.spyOn(global, "fetch").mockResolvedValue(json({ message: "ok" }, 202));
    wrap(<VerifyEmailBanner email="sara@nile.eg" trialPending />);
    expect(screen.getByText(/activate your free trial points.*sara@nile\.eg/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Resend email" }));
    expect(await screen.findByText("Sent. Check your inbox.")).toBeInTheDocument();
    expect(spy.mock.calls.some(([u, i]) => String(u).endsWith("/auth/email/resend") && i?.method === "POST")).toBe(true);
  });

  it("tells the user when they hit the resend limit", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(error(429, "rate_limited"));
    wrap(<VerifyEmailBanner email="sara@nile.eg" trialPending={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Resend email" }));
    expect(await screen.findByText("Too many requests. Try again in an hour.")).toBeInTheDocument();
  });
});
