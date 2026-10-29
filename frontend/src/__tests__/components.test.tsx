import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoBadge, PriorityBadge, ProviderStatusBadge, ScorePill, StatusBadge, VerificationBadge } from "@/components/badges";
import { Progress } from "@/components/ui/primitives";
import { ErrorState } from "@/components/ui/states";
import { LoginForm } from "@/features/auth/login-form";
import { I18nProvider, useI18n } from "@/i18n/provider";
import { ApiError } from "@/lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nProvider>
      <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
    </I18nProvider>,
  );
}

beforeEach(() => {
  window.localStorage.setItem("lh-locale", "en");
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.setItem("lh-locale", "en");
});

describe("status & data badges", () => {
  it("renders campaign status, priority and verification labels", () => {
    wrap(
      <>
        <StatusBadge status="partially_completed" />
        <PriorityBadge priority="needs_review" />
        <VerificationBadge status="discovered" />
        <ProviderStatusBadge status="requires_api_key" />
        <DemoBadge />
      </>,
    );
    expect(screen.getByText("Partially completed")).toBeInTheDocument();
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(screen.getByText("Discovered")).toBeInTheDocument();
    expect(screen.getByText("Requires API key")).toBeInTheDocument();
    expect(screen.getByText("DEMO MODE")).toBeInTheDocument();
  });

  it("shows a dash for missing scores instead of a fake value", () => {
    wrap(<ScorePill score={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("progress", () => {
  it("is indeterminate when progress cannot be measured", () => {
    render(<Progress value={null} label="x" />);
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  });
  it("reports measured progress", () => {
    render(<Progress value={42.4} label="x" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
  });
});

describe("error state", () => {
  it("shows the API error message and a retry action", async () => {
    const retry = vi.fn();
    wrap(<ErrorState error={new ApiError(500, "x", "Database unavailable")} onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Database unavailable");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalled();
  });
});

describe("i18n", () => {
  function Probe() {
    const { t, setLocale, dir } = useI18n();
    return (
      <button onClick={() => setLocale("ar")} data-dir={dir}>
        {t.nav.campaigns}
      </button>
    );
  }
  it("switches to Arabic and RTL", async () => {
    wrap(<Probe />);
    await userEvent.click(screen.getByRole("button", { name: "Campaigns" }));
    expect(screen.getByRole("button", { name: "الحملات" })).toHaveAttribute("data-dir", "rtl");
    expect(document.documentElement.dir).toBe("rtl");
  });
});

describe("event messages", () => {
  function Event({ data, message }: { data: unknown; message: string }) {
    const { eventText, setLocale } = useI18n();
    return (
      <button onClick={() => setLocale("ar")}>{eventText(data, message)}</button>
    );
  }
  it("renders templated events in Arabic and keeps the raw message for untagged ones", async () => {
    wrap(
      <>
        <Event data={{ t: "provider_done", p: { provider: "google_maps", count: 40 } }} message="Google Maps returned 40" />
        <Event data={{}} message="Legacy English line" />
      </>,
    );
    expect(screen.getByText("Google Maps returned 40 businesses")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Google Maps returned 40 businesses"));
    expect(screen.getByText("خرائط جوجل رجّع 40 شركة")).toBeInTheDocument();
    expect(screen.getByText("Legacy English line")).toBeInTheDocument();
  });
});

describe("login form", () => {
  it("validates input before calling the API", async () => {
    const fetchSpy = vi.spyOn(global, "fetch");
    wrap(<LoginForm />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findAllByRole("alert")).not.toHaveLength(0);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("shows an error for invalid credentials", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "unauthorized", message: "Invalid" } }), { status: 401 }),
    );
    Object.defineProperty(window, "location", { value: { ...window.location, pathname: "/login", search: "" }, writable: true });
    wrap(<LoginForm />);
    await userEvent.type(screen.getByLabelText("Email"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await act(async () => {
      await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    });
    expect(await screen.findByText("Invalid email or password")).toBeInTheDocument();
  });
});
