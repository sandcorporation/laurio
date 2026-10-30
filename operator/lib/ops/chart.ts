// 운영 지표 차트(#829)의 순수 계산 — 눈금·경로·막대 좌표. 차트 라이브러리를 들이지 않고 인라인 SVG 로 그린다.
// 값이 0·null·빈 배열이어도 깨지지 않게(NaN 좌표가 나오지 않게) 한다.

/** 버킷마다 한 칸. null 은 「그 분위수의 관측이 없다」 — 0 과 다르다. */
export type Cell = number | null;

const NICE_STEPS = [1, 2, 2.5, 5, 10];

/** 0 부터 max 까지 `intervals` 칸으로 나눈 보기 좋은 눈금. max<=0 이거나 유한하지 않으면 0..1. */
export function niceScale(max: number, intervals = 4): { max: number; ticks: number[] } {
  const safe = Number.isFinite(max) && max > 0 ? max : 0;
  if (safe === 0) return { max: 1, ticks: Array.from({ length: intervals + 1 }, (_, i) => i / intervals) };
  const raw = safe / intervals;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = (NICE_STEPS.find((s) => s * magnitude >= raw - 1e-12) ?? 10) * magnitude;
  const ticks = Array.from({ length: intervals + 1 }, (_, i) => Number((i * step).toPrecision(12)));
  return { max: ticks[intervals], ticks };
}

export function seriesMax(series: readonly (readonly Cell[])[]): number {
  let max = 0;
  for (const values of series) for (const v of values) if (v !== null && Number.isFinite(v) && v > max) max = v;
  return max;
}

/** 쌓은 막대의 최대 높이 — 버킷마다 시리즈 값의 합 중 가장 큰 것. */
export function stackedMax(series: readonly (readonly Cell[])[]): number {
  const length = Math.max(0, ...series.map((s) => s.length));
  let max = 0;
  for (let i = 0; i < length; i++) {
    let sum = 0;
    for (const s of series) sum += s[i] ?? 0;
    if (sum > max) max = sum;
  }
  return max;
}

function xAt(index: number, count: number, width: number): number {
  return count <= 1 ? width / 2 : (index / (count - 1)) * width;
}

function yAt(value: number, max: number, height: number): number {
  const ratio = max > 0 ? Math.min(Math.max(value / max, 0), 1) : 0;
  return height - ratio * height;
}

const fixed = (n: number) => Number(n.toFixed(2));

/** 선 하나의 SVG path. null 칸에서 선을 끊는다(0 으로 이어 붙이지 않는다). 점이 없으면 빈 문자열. */
export function linePath(values: readonly Cell[], max: number, width: number, height: number): string {
  const parts: string[] = [];
  let pen = false;
  values.forEach((v, i) => {
    if (v === null || !Number.isFinite(v)) {
      pen = false;
      return;
    }
    const x = fixed(xAt(i, values.length, width));
    const y = fixed(yAt(v, max, height));
    parts.push(`${pen ? "L" : "M"}${x} ${y}`);
    pen = true;
  });
  return parts.join(" ");
}

/** 이어진 점이 하나뿐이라 선이 안 보이는 칸 — 점으로 찍는다. */
export function isolatedPoints(values: readonly Cell[], max: number, width: number, height: number) {
  const out: { x: number; y: number }[] = [];
  values.forEach((v, i) => {
    if (v === null || !Number.isFinite(v)) return;
    const prev = values[i - 1];
    const next = values[i + 1];
    const hasPrev = prev !== null && prev !== undefined && Number.isFinite(prev);
    const hasNext = next !== null && next !== undefined && Number.isFinite(next);
    if (!hasPrev && !hasNext) out.push({ x: fixed(xAt(i, values.length, width)), y: fixed(yAt(v, max, height)) });
  });
  return out;
}

export type BarRect = { x: number; y: number; width: number; height: number; series: number; bucket: number };

/** 쌓은 막대 좌표. 시리즈 순서가 아래에서 위로. 높이 0 인 칸은 만들지 않는다. */
export function stackedBars(
  series: readonly (readonly Cell[])[],
  max: number,
  width: number,
  height: number,
  gap = 0.2,
): BarRect[] {
  const count = Math.max(0, ...series.map((s) => s.length));
  if (count === 0) return [];
  const slot = width / count;
  const barWidth = Math.max(slot * (1 - gap), 0.5);
  const rects: BarRect[] = [];
  for (let b = 0; b < count; b++) {
    let acc = 0;
    series.forEach((s, si) => {
      const v = s[b];
      if (v === null || v === undefined || !Number.isFinite(v) || v <= 0) return;
      const top = yAt(acc + v, max, height);
      const bottom = yAt(acc, max, height);
      acc += v;
      if (bottom - top <= 0) return;
      rects.push({
        x: fixed(b * slot + (slot - barWidth) / 2),
        y: fixed(top),
        width: fixed(barWidth),
        height: fixed(bottom - top),
        series: si,
        bucket: b,
      });
    });
  }
  return rects;
}

/** x 축에 찍을 버킷 인덱스 — 처음·끝을 포함해 균등하게 최대 `count` 개. */
export function labelIndexes(length: number, count = 4): number[] {
  if (length <= 0) return [];
  if (length === 1) return [0];
  const n = Math.min(count, length);
  return Array.from(new Set(Array.from({ length: n }, (_, i) => Math.round((i * (length - 1)) / (n - 1)))));
}

const SEOUL_HOUR = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false });
const SEOUL_DAY = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric" });

/** 버킷 시작 시각의 x 축 라벨(서울). 하루 이상을 가로지르면 날짜를 앞에 붙이고, 7일처럼 시간 단위 버킷이면 날짜+시.
 * 파싱이 안 되면 빈 문자열. */
export function bucketLabel(iso: string, bucketSeconds: number, withDate = false): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (bucketSeconds >= 3600) return `${SEOUL_DAY.format(d)} ${SEOUL_HOUR.format(d).slice(0, 2)}시`;
  return withDate ? `${SEOUL_DAY.format(d)} ${SEOUL_HOUR.format(d)}` : SEOUL_HOUR.format(d);
}

/** 첫·끝 버킷이 20시간 넘게 떨어져 있으면 라벨에 날짜가 있어야 어느 날인지 읽힌다. */
export function spansDays(starts: readonly string[]): boolean {
  if (starts.length < 2) return false;
  const first = new Date(starts[0]).getTime();
  const last = new Date(starts[starts.length - 1]).getTime();
  return Number.isFinite(first) && Number.isFinite(last) && last - first >= 20 * 3600 * 1000;
}
