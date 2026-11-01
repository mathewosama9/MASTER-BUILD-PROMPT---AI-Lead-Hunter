import { describe, expect, it } from "vitest";

import { linkedinProfileUrl, safeHttpUrl } from "@/features/leads/links";

describe("links from scraped data", () => {
  it("only lets http(s) URLs become links", () => {
    expect(safeHttpUrl("https://smile-dental.sa/team")).toBe("https://smile-dental.sa/team");
    expect(safeHttpUrl("http://smile-dental.sa")).toBe("http://smile-dental.sa/");
    expect(safeHttpUrl("javascript:alert(1)//https://smile.sa")).toBeNull();
    expect(safeHttpUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeHttpUrl("Dr. Omar Khaled")).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
  });

  it("accepts only real LinkedIn personal profiles", () => {
    expect(linkedinProfileUrl("https://www.linkedin.com/in/omar-khaled")).toBe("https://www.linkedin.com/in/omar-khaled");
    expect(linkedinProfileUrl("https://sa.linkedin.com/in/omar")).toBe("https://sa.linkedin.com/in/omar");
    // The substring check this replaced would have accepted every one of these.
    expect(linkedinProfileUrl("javascript:alert(1)//linkedin.com/in/x")).toBeNull();
    expect(linkedinProfileUrl("https://evil.example/linkedin.com/in/x")).toBeNull();
    expect(linkedinProfileUrl("https://linkedin.com.evil.example/in/x")).toBeNull();
    expect(linkedinProfileUrl("http://www.linkedin.com/in/x")).toBeNull();
    expect(linkedinProfileUrl("https://www.linkedin.com/company/smile")).toBeNull();
  });
});
