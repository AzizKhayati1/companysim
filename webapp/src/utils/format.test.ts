import { describe, expect, it } from "vitest";
import { formatCurrency, formatDateTime } from "./format";

describe("formatCurrency", () => {
  it("pins to en-US formatting regardless of runtime default locale", () => {
    // Regression guard for §5.5: toLocaleString() without an explicit
    // locale renders differently depending on the environment's default
    // (e.g. "185 236" with a space thousands separator instead of
    // "185,236"). This asserts the comma-separated, no-decimal shape.
    expect(formatCurrency(185236.41)).toBe("185,236");
  });

  it("rounds to whole dollars", () => {
    expect(formatCurrency(999.6)).toBe("1,000");
  });

  it("handles small amounts without a thousands separator", () => {
    expect(formatCurrency(42)).toBe("42");
  });
});

describe("formatDateTime", () => {
  it("pins to en-US date/time formatting", () => {
    const result = formatDateTime("2026-03-05T14:30:00Z");
    // en-US renders month/day/year with a slash and a 12-hour clock —
    // assert the shape rather than an exact string (still timezone-shifted
    // by the test runner's TZ, but the *locale* is what §5.5 was about).
    expect(result).toMatch(/^\d{1,2}\/\d{1,2}\/\d{4}/);
  });
});
