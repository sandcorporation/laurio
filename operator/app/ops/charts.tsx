// 운영 지표 차트(#829) — 의존성 없는 인라인 SVG. 좌표 계산은 lib/ops/chart.ts(순수 함수).
// 면(plot)만 SVG 이고 눈금·범례 글자는 HTML 이다 — 좁은 화면에서 SVG 가 줄어도 글자가 같이 줄지 않는다.
// 색은 tokens.css 토큰만(다크는 토큰이 light-dark 로 따라온다). 화면에는 라벨·값만 둔다.
import {
  type Cell,
  bucketLabel,
  isolatedPoints,
  labelIndexes,
  spansDays,
  linePath,
  niceScale,
  seriesMax,
  stackedBars,
  stackedMax,
} from "@/lib/ops/chart";

const W = 600;
const H = 140;
const TICK_INTERVALS = 4;

export type ChartSeries = {
  key: string;
  label: string;
  color: string;
  values: readonly Cell[];
};

export const INK = (percent: number) => `color-mix(in srgb, var(--color-ink) ${percent}%, transparent)`;
export const VERIFIED = "var(--color-verified)";
export const ATTENTION = "var(--color-attention)";

function Legend({ series }: { series: readonly ChartSeries[] }) {
  return (
    <ul className="flex flex-wrap gap-x-3.5 gap-y-1 px-4 pb-3 text-[12px] text-ink/62">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-2 w-2.5" style={{ background: s.color }} />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

function Frame({
  title,
  testId,
  series,
  ticks,
  tickLabel,
  starts,
  bucketSeconds,
  empty,
  withDate,
  children,
}: {
  title: string;
  testId: string;
  series: readonly ChartSeries[];
  ticks: readonly number[];
  tickLabel: (value: number) => string;
  starts: readonly string[];
  bucketSeconds: number;
  empty: boolean;
  withDate: boolean;
  children: React.ReactNode;
}) {
  const xs = labelIndexes(starts.length, withDate ? 3 : 4);
  return (
    <figure data-testid={testId} data-empty={empty ? "true" : "false"} className="m-0 border border-rule">
      <figcaption className="border-b border-rule px-4 py-2 text-[11px] tracking-[0.06em] text-ink/45">{title}</figcaption>
      <div className="grid grid-cols-[3.25rem_minmax(0,1fr)] gap-x-2 px-4 pt-3">
        <div className="relative font-mono text-[11px] text-ink/45" style={{ height: H }} aria-hidden>
          {ticks.map((t, i) => (
            <span
              key={i}
              className="absolute right-0 -translate-y-1/2 leading-none"
              style={{ top: `${100 - (i / TICK_INTERVALS) * 100}%` }}
            >
              {tickLabel(t)}
            </span>
          ))}
        </div>
        <div className="relative" style={{ height: H }}>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={title} className="block h-full w-full overflow-visible">
            {ticks.map((_, i) => {
              const y = H - (i / TICK_INTERVALS) * H;
              return (
                <line
                  key={i}
                  x1={0}
                  x2={W}
                  y1={y}
                  y2={y}
                  stroke={INK(i === 0 ? 30 : 12)}
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                />
              );
            })}
            {children}
          </svg>
          {empty && (
            <span className="absolute inset-0 flex items-center justify-center font-mono text-[13px] text-ink/30">—</span>
          )}
        </div>
        <div />
        <div className="relative mb-1 h-4 font-mono text-[11px] text-ink/45" aria-hidden>
          {xs.map((i, n) => (
            <span
              key={i}
              className="absolute whitespace-nowrap"
              style={
                n === 0
                  ? { left: 0 }
                  : n === xs.length - 1
                    ? { right: 0 }
                    : { left: `${(i / Math.max(starts.length - 1, 1)) * 100}%`, transform: "translateX(-50%)" }
              }
            >
              {bucketLabel(starts[i], bucketSeconds, withDate)}
            </span>
          ))}
        </div>
      </div>
      <Legend series={series} />
    </figure>
  );
}

type Common = {
  title: string;
  testId: string;
  series: readonly ChartSeries[];
  starts: readonly string[];
  bucketSeconds: number;
  format: (value: number) => string;
};

/** 쌓은 막대 — 결과별 호출·상태코드·토큰. */
export function StackedBarChart({ title, testId, series, starts, bucketSeconds, format }: Common) {
  const values = series.map((s) => s.values);
  const { max, ticks } = niceScale(stackedMax(values), TICK_INTERVALS);
  const rects = stackedBars(values, max, W, H);
  return (
    <Frame
      title={title}
      testId={testId}
      series={series}
      ticks={ticks}
      tickLabel={format}
      starts={starts}
      bucketSeconds={bucketSeconds}
      empty={rects.length === 0}
      withDate={spansDays(starts)}
    >
      {rects.map((r) => (
        <rect key={`${r.bucket}-${r.series}`} x={r.x} y={r.y} width={r.width} height={r.height} fill={series[r.series].color}>
          <title>{`${bucketLabel(starts[r.bucket] ?? "", bucketSeconds, spansDays(starts))} ${series[r.series].label} ${format(series[r.series].values[r.bucket] ?? 0)}`}</title>
        </rect>
      ))}
    </Frame>
  );
}

/** 꺾은선 — 지연·초당 요청·5xx 비율·큐 대기. null 은 선을 끊는다. */
export function LineChart({ title, testId, series, starts, bucketSeconds, format }: Common) {
  const values = series.map((s) => s.values);
  const { max, ticks } = niceScale(seriesMax(values), TICK_INTERVALS);
  const hasData = values.some((v) => v.some((c) => c !== null));
  return (
    <Frame
      title={title}
      testId={testId}
      series={series}
      ticks={ticks}
      tickLabel={format}
      starts={starts}
      bucketSeconds={bucketSeconds}
      empty={!hasData}
      withDate={spansDays(starts)}
    >
      {series.map((s) => (
        <g key={s.key} stroke={s.color} fill="none">
          <path d={linePath(s.values, max, W, H)} strokeWidth={1.75} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          {isolatedPoints(s.values, max, W, H).map((p, i) => (
            <path key={i} d={`M${p.x} ${p.y}h0`} strokeWidth={5} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          ))}
        </g>
      ))}
    </Frame>
  );
}
