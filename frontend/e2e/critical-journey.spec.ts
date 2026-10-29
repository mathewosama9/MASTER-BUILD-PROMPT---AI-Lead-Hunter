import { expect, test } from "@playwright/test";

const EMAIL = process.env.E2E_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_PASSWORD ?? "ChangeMe-12345";

test("login → create demo campaign → live monitor completes → lead detail → CSV export", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("DEMO MODE").first()).toBeVisible();

  // Wizard
  await page.getByRole("link", { name: "New campaign" }).first().click();
  await expect(page.getByRole("heading", { name: "New research campaign" })).toBeVisible();
  await page.getByLabel("Country").selectOption("SA");
  await page.getByLabel("City").fill("Jeddah");
  await page.getByRole("button", { name: "Next" }).click();
  // Step 2 validation: industry is required
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Choose or type an industry")).toBeVisible();
  await page.getByLabel("Industry / category").fill("dental_clinics");
  await page.getByRole("button", { name: "Appointment Scheduling Automation" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  // Sources: real providers without keys are labelled honestly
  await expect(page.getByText("Requires API key").first()).toBeVisible();
  await page.getByRole("checkbox", { name: "Demo fixtures" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByLabel("Target lead count").fill("6");
  await page.getByLabel("Max companies to inspect").fill("8");
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Estimated usage")).toBeVisible();
  await page.getByRole("button", { name: "Start campaign" }).click();

  // Live monitor
  await expect(page.getByText("Live monitor")).toBeVisible();
  await expect(page.getByText("Completed").first()).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("6 / 8")).toBeVisible(); // requested vs found

  // Results → lead detail
  const firstLead = page.locator("table a[href^='/leads/']").first();
  await expect(firstLead).toBeVisible();
  await firstLead.click();
  await expect(page.getByText("Scoring details")).toBeVisible();
  await expect(page.getByText("Evidence & references")).toBeVisible();
  await expect(page.getByText("Rule-based analysis (demo)")).toBeVisible();

  // Export CSV from the leads page
  await page.getByRole("link", { name: "Leads" }).click();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "CSV" }).click()]);
  expect(download.suggestedFilename()).toMatch(/^leads-.*\.csv$/);
});

test("Arabic locale switches the layout to RTL", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "العربية" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByText("تسجيل الدخول إلى مساحة العمل")).toBeVisible();
});
