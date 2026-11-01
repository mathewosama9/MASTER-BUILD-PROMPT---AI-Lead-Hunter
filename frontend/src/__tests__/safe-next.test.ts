import { describe, expect, it } from "vitest";

import { safeNextPath } from "@/lib/utils";

const origin = "https://app.example.com";

describe("safeNextPath", () => {
  it("keeps same-origin paths with their query", () => {
    expect(safeNextPath("/leads?status=new", origin)).toBe("/leads?status=new");
    expect(safeNextPath(`${origin}/campaigns/1`, origin)).toBe("/campaigns/1");
  });

  it.each([
    "//evil.com/x",
    "/\\evil.com",
    "\\\\evil.com",
    "https://evil.com/",
    "javascript:alert(1)",
    "http://app.example.com/", // different scheme = different origin
  ])("rejects %s", (next) => {
    expect(safeNextPath(next, origin)).toBe("/");
  });

  it("falls back when next is missing", () => {
    expect(safeNextPath(null, origin)).toBe("/");
    expect(safeNextPath("", origin, "/app")).toBe("/app");
  });
});
