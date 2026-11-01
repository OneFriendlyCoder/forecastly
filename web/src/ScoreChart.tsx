import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ScorePoint } from "./api";
import { formatDate, formatScore } from "./format";

type Point = { time: number; percent: number };

const TICKS = 5;

// Scores arrive unevenly, so the ticks are spaced by time, not by data point.
function evenTicks(first: number, last: number) {
  const ticks = Array.from({ length: TICKS }, (_, i) => first + ((last - first) * i) / (TICKS - 1));
  return [...new Set(ticks)];
}

const shortDate = (time: number) => formatDate(new Date(time).toISOString());

function ChartTooltip({ active, payload }: { active?: boolean; payload?: readonly { payload?: Point }[] }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="chart-tooltip">
      <strong>{point.percent}%</strong>
      <span>{shortDate(point.time)}</span>
    </div>
  );
}

function EndDot({ cx, cy, index, last }: { cx?: number; cy?: number; index?: number; last: number }) {
  if (index !== last) return <g key={index} />;
  return <circle key={index} cx={cx} cy={cy} r={5} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={2} />;
}

export function ScoreChart({ scores }: { scores: ScorePoint[] }) {
  const points: Point[] = scores.map((s) => ({ time: Date.parse(s.as_of), percent: Math.round(s.score * 100) }));
  return (
    <>
      <div className="chart" role="img" aria-label={`Win chance over time, now ${points.at(-1)?.percent}%`}>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis
              dataKey="time"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              ticks={evenTicks(points[0].time, points[points.length - 1].time)}
              tickFormatter={shortDate}
              minTickGap={24}
              interval="preserveStartEnd"
              tick={{ fill: "var(--text-muted)", fontSize: 12 }}
              stroke="var(--grid)"
              tickLine={false}
            />
            <YAxis
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              tickFormatter={(value) => `${value}%`}
              tick={{ fill: "var(--text-muted)", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={ChartTooltip} cursor={{ stroke: "var(--text-muted)", strokeWidth: 1 }} />
            <Line
              dataKey="percent"
              stroke="var(--series-1)"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              dot={(props) => <EndDot {...props} last={points.length - 1} />}
              activeDot={{ r: 5, fill: "var(--series-1)", stroke: "var(--surface)", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <details className="chart-table">
        <summary>Show scores as a table</summary>
        <table>
          <thead>
            <tr><th>Date</th><th className="number">Win chance</th></tr>
          </thead>
          <tbody>
            {scores.map((s) => (
              <tr key={s.as_of}><td>{formatDate(s.as_of)}</td><td className="number">{formatScore(s.score)}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}
