import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EventMarker } from "../utils/eventMarkers";

interface FanChartProps {
  rows: Record<string, number>[];
  metric: string;
  title: string;
  color?: string;
  singleRun?: boolean;
  markers?: EventMarker[];
}

export default function FanChart({
  rows,
  metric,
  title,
  color = "#6d28d9",
  singleRun = false,
  markers = [],
}: FanChartProps) {
  const data = rows.map((r) => {
    if (singleRun) {
      return { tick: r.tick, value: r[metric] };
    }
    const p05 = r[`${metric}_p05`] ?? 0;
    const p50 = r[`${metric}_p50`] ?? 0;
    const p95 = r[`${metric}_p95`] ?? 0;
    return { tick: r.tick, bandBase: p05, bandHeight: p95 - p05, p50 };
  });

  return (
    <div>
      <h3>{title}</h3>
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
          <XAxis dataKey="tick" fontSize={11} />
          <YAxis fontSize={11} />
          <Tooltip />
          {markers.map((m) => (
            <ReferenceLine
              key={m.at_tick}
              x={m.at_tick}
              stroke="var(--text-3)"
              strokeDasharray="3 3"
              label={{ value: m.label, position: "top", fontSize: 9, fill: "var(--text-3)" }}
            />
          ))}
          {singleRun ? (
            <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} />
          ) : (
            <>
              <Area
                type="monotone"
                dataKey="bandBase"
                stackId="band"
                stroke="none"
                fill="transparent"
              />
              <Area
                type="monotone"
                dataKey="bandHeight"
                stackId="band"
                stroke="none"
                fill={color}
                fillOpacity={0.25}
              />
              <Line type="monotone" dataKey="p50" stroke={color} strokeWidth={2} dot={false} />
            </>
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
