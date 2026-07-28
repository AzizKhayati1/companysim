export interface EventMarker {
  at_tick: number;
  label: string;
}

/** Groups scenario events by the tick they fire at, into one chart
 * marker per tick — "Layoff" for a single event, "Layoff +2" when
 * multiple events share a tick (only the first event's label is shown,
 * since a marker only has room for one line of text). */
export function buildEventMarkers(
  events: { at_tick: number; type: string }[],
  labels: Record<string, string>,
): EventMarker[] {
  const byTick = new Map<number, string[]>();
  for (const e of events) {
    const list = byTick.get(e.at_tick) ?? [];
    list.push(labels[e.type] ?? e.type);
    byTick.set(e.at_tick, list);
  }
  return Array.from(byTick.entries())
    .sort(([a], [b]) => a - b)
    .map(([at_tick, types]) => ({
      at_tick,
      label: types.length === 1 ? types[0] : `${types[0]} +${types.length - 1}`,
    }));
}
