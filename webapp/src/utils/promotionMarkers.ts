// A risk-score-over-time chart's points are scored against whichever model
// is in production *at the moment the run happens* — for an employee whose
// own record hasn't been edited, that's the only thing that can move their
// score between runs. So a jump from one point to the next is explained by
// pinpointing a promotion that landed strictly between those two runs —
// not by any promotion in the model's history, most of which predate the
// org's own points and have nothing to do with this particular jump.

export interface PromotionMarker {
  index: number;
  label: string;
}

// Risk-snapshot timestamps are written as UTC but lose their offset on the
// SQLite round-trip, coming back as a naive "2026-07-27T16:28:54.437256"
// string; the promotion log is written straight to a JSON file and keeps
// its explicit "+00:00". Left alone, the browser's Date parser treats the
// naive string as *local* time, silently shifting every comparison below
// by the viewer's UTC offset. Both are real UTC instants, so normalize any
// string missing an explicit offset to UTC before comparing.
function toUtcMillis(timestamp: string): number {
  const hasOffset = /[zZ]|[+-]\d{2}:\d{2}$/.test(timestamp);
  return new Date(hasOffset ? timestamp : `${timestamp}Z`).getTime();
}

export function buildPromotionMarkers(
  points: { computed_at: string }[],
  promotions: { timestamp: string; decision: string }[],
): PromotionMarker[] {
  const promotedTimestamps = promotions
    .filter((p) => p.decision === "PROMOTE")
    .map((p) => toUtcMillis(p.timestamp));

  const markers: PromotionMarker[] = [];
  for (let i = 1; i < points.length; i++) {
    const prevTs = toUtcMillis(points[i - 1].computed_at);
    const currTs = toUtcMillis(points[i].computed_at);
    const count = promotedTimestamps.filter((ts) => ts > prevTs && ts <= currTs).length;
    if (count > 0) {
      markers.push({ index: i, label: count === 1 ? "Model promoted" : `Model promoted +${count - 1}` });
    }
  }
  return markers;
}
