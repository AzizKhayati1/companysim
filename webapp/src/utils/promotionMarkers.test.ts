import { describe, expect, it } from "vitest";
import { buildPromotionMarkers } from "./promotionMarkers";

const POINTS = [
  { computed_at: "2026-07-14T10:00:00Z" },
  { computed_at: "2026-07-18T10:00:00Z" },
  { computed_at: "2026-07-20T09:00:00Z" },
  { computed_at: "2026-07-20T11:00:00Z" },
  { computed_at: "2026-07-27T10:00:00Z" },
];

describe("buildPromotionMarkers", () => {
  it("returns an empty list for no points or no promotions", () => {
    expect(buildPromotionMarkers([], [{ timestamp: "2026-07-20T10:00:00Z", decision: "PROMOTE" }])).toEqual([]);
    expect(buildPromotionMarkers(POINTS, [])).toEqual([]);
  });

  it("returns an empty list for a single point — no prior point to contrast against", () => {
    const markers = buildPromotionMarkers(
      [POINTS[0]],
      [{ timestamp: "2026-07-10T00:00:00Z", decision: "PROMOTE" }],
    );
    expect(markers).toEqual([]);
  });

  it("attaches a promotion to the point immediately after it lands", () => {
    const markers = buildPromotionMarkers(POINTS, [
      { timestamp: "2026-07-19T00:00:00Z", decision: "PROMOTE" },
    ]);
    expect(markers).toEqual([{ index: 2, label: "Model promoted" }]);
  });

  it("ignores BLOCK decisions — only a real promotion moves the live model", () => {
    const markers = buildPromotionMarkers(POINTS, [
      { timestamp: "2026-07-19T00:00:00Z", decision: "BLOCK" },
    ]);
    expect(markers).toEqual([]);
  });

  it("ignores promotions from before the org's first recorded point", () => {
    const markers = buildPromotionMarkers(POINTS, [
      { timestamp: "2026-01-01T00:00:00Z", decision: "PROMOTE" },
    ]);
    expect(markers).toEqual([]);
  });

  it("ignores a promotion that hasn't affected any recorded run yet", () => {
    const markers = buildPromotionMarkers(POINTS, [
      { timestamp: "2026-08-01T00:00:00Z", decision: "PROMOTE" },
    ]);
    expect(markers).toEqual([]);
  });

  it("appends a +N count when multiple promotions land in the same gap", () => {
    const markers = buildPromotionMarkers(POINTS, [
      { timestamp: "2026-07-19T00:00:00Z", decision: "PROMOTE" },
      { timestamp: "2026-07-19T12:00:00Z", decision: "PROMOTE" },
      { timestamp: "2026-07-19T18:00:00Z", decision: "PROMOTE" },
    ]);
    expect(markers).toEqual([{ index: 2, label: "Model promoted +2" }]);
  });

  it("treats a naive (offset-less) point timestamp as UTC, matching an explicit-offset promotion timestamp", () => {
    // Regression test: risk-snapshot timestamps come back from the DB
    // without a timezone suffix (e.g. "2026-07-20T09:30:00"), while the
    // promotion log keeps its explicit "+00:00" — both are real UTC
    // instants and must compare equal regardless of the viewer's local
    // timezone, not drift by the browser's UTC offset.
    const naivePoints = [
      { computed_at: "2026-07-20T09:00:00" },
      { computed_at: "2026-07-20T11:00:00" },
    ];
    const markers = buildPromotionMarkers(naivePoints, [
      { timestamp: "2026-07-20T10:00:00+00:00", decision: "PROMOTE" },
    ]);
    expect(markers).toEqual([{ index: 1, label: "Model promoted" }]);
  });

  it("returns one marker per gap that had a promotion, sorted ascending", () => {
    const markers = buildPromotionMarkers(POINTS, [
      { timestamp: "2026-07-26T00:00:00Z", decision: "PROMOTE" },
      { timestamp: "2026-07-19T00:00:00Z", decision: "PROMOTE" },
    ]);
    expect(markers.map((m) => m.index)).toEqual([2, 4]);
  });
});
