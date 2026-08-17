import type { LabelPerformancePoint } from "./dashboard.types";

type LabelPerformanceChartProps = {
  points: LabelPerformancePoint[];
  summary: string;
};

const width = 640;
const height = 280;
const padding = {
  bottom: 38,
  left: 22,
  right: 22,
  top: 18,
};

function toPath(points: Array<{ x: number; y: number }>) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
}

export function LabelPerformanceChart({ points, summary }: LabelPerformanceChartProps) {
  if (points.length === 0) {
    return null;
  }

  const values = points.map((point) => point.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const valueRange = maxValue - minValue || 1;
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const coordinates = points.map((point, index) => {
    const x =
      padding.left +
      (points.length === 1 ? chartWidth : (index / (points.length - 1)) * chartWidth);
    const y = padding.top + chartHeight - ((point.value - minValue) / valueRange) * chartHeight;

    return { ...point, x, y };
  });
  const linePath = toPath(coordinates);
  const areaPath = `${linePath} L ${coordinates.at(-1)?.x ?? padding.left} ${
    height - padding.bottom
  } L ${padding.left} ${height - padding.bottom} Z`;
  const firstPoint = coordinates[0];
  const lastPoint = coordinates.at(-1);
  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((step) => padding.top + chartHeight * step);
  const summaryId = "label-performance-chart-summary";
  const tableId = "label-performance-chart-data";

  return (
    <figure
      aria-describedby={`${summaryId} ${tableId}`}
      className="min-w-0 rounded-[16px] border border-slate-700/60 bg-slate-950/30 p-2.5 sm:p-4"
    >
      <figcaption className="sr-only" id={summaryId}>
        {summary}
      </figcaption>
      <div className="h-56 w-full sm:h-64 lg:h-[17rem]">
        <svg
          aria-hidden="true"
          className="h-full w-full overflow-visible"
          preserveAspectRatio="none"
          viewBox={`0 0 ${width} ${height}`}
        >
          <defs>
            <linearGradient id="label-performance-area" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#67e8f9" stopOpacity="0.28" />
              <stop offset="58%" stopColor="#34d399" stopOpacity="0.11" />
              <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
            </linearGradient>
          </defs>
          {gridLines.map((lineY) => (
            <line
              key={lineY}
              stroke="rgb(148 163 184 / 0.14)"
              strokeWidth="1"
              x1={padding.left}
              x2={width - padding.right}
              y1={lineY}
              y2={lineY}
            />
          ))}
          <path d={areaPath} fill="url(#label-performance-area)" />
          <path
            d={linePath}
            fill="none"
            stroke="#67e8f9"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="3"
            vectorEffect="non-scaling-stroke"
          />
          {coordinates.map((point, index) => (
            <circle
              cx={point.x}
              cy={point.y}
              fill={index === coordinates.length - 1 ? "#a7f3d0" : "#67e8f9"}
              key={`${point.date}-${point.value}`}
              r={index === coordinates.length - 1 ? 5 : 3}
              stroke="#020617"
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {firstPoint ? (
            <text fill="#94a3b8" fontSize="12" x={firstPoint.x} y={height - 12}>
              {firstPoint.label}
            </text>
          ) : null}
          {lastPoint ? (
            <text fill="#94a3b8" fontSize="12" textAnchor="end" x={lastPoint.x} y={height - 12}>
              {lastPoint.label}
            </text>
          ) : null}
        </svg>
      </div>
      <table className="sr-only" id={tableId}>
        <caption>Performance chart data</caption>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Value</th>
          </tr>
        </thead>
        <tbody>
          {points.map((point) => (
            <tr key={`${point.date}-${point.value}`}>
              <td>{point.label}</td>
              <td>{point.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
