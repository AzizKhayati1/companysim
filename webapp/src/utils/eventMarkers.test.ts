import { describe, expect, it } from "vitest";
import { buildEventMarkers } from "./eventMarkers";

const LABELS: Record<string, string> = {
  layoff: "Layoff",
  hire: "Hire",
  reorg: "Reorg",
};

describe("buildEventMarkers", () => {
  it("returns an empty list for no events", () => {
    expect(buildEventMarkers([], LABELS)).toEqual([]);
  });

  it("labels a single event at a tick with just its type", () => {
    const markers = buildEventMarkers([{ at_tick: 3, type: "layoff" }], LABELS);
    expect(markers).toEqual([{ at_tick: 3, label: "Layoff" }]);
  });

  it("appends a +N count when multiple events share a tick", () => {
    const markers = buildEventMarkers(
      [
        { at_tick: 5, type: "layoff" },
        { at_tick: 5, type: "hire" },
        { at_tick: 5, type: "reorg" },
      ],
      LABELS,
    );
    expect(markers).toEqual([{ at_tick: 5, label: "Layoff +2" }]);
  });

  it("returns one marker per distinct tick, sorted ascending", () => {
    const markers = buildEventMarkers(
      [
        { at_tick: 10, type: "reorg" },
        { at_tick: 2, type: "layoff" },
        { at_tick: 6, type: "hire" },
      ],
      LABELS,
    );
    expect(markers.map((m) => m.at_tick)).toEqual([2, 6, 10]);
  });

  it("falls back to the raw type string when no label is known", () => {
    const markers = buildEventMarkers([{ at_tick: 1, type: "mystery_event" }], LABELS);
    expect(markers).toEqual([{ at_tick: 1, label: "mystery_event" }]);
  });
});
