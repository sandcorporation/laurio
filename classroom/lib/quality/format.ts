// 완성도 화면의 표시값(#883·#904) — 계산은 백엔드(`core.quality_review`, 지금 배점으로)가 하고 여기는 글자만 만든다.
import type { QualityEstimate } from "./api";

/** 점수를 소수 첫째 자리까지. */
export function formatPoints(value: number): string {
  return (Math.round(value * 10) / 10).toFixed(1);
}

/** 「37.4 / 45점」 — 합은 소수 첫째 자리, 만점은 배점 합. 등수는 이 표시값이 아니라 백엔드의 정수 합으로 매긴다. */
export function formatQualityTotal(total: number, maxTotal: number): string {
  return `${formatPoints(total)} / ${maxTotal}점`;
}

/** 예상 비용 — 단가를 모르면 「단가 모름」, 100원 아래는 「100원 미만」, 그 위는 10원 단위 반올림. */
export function formatQualityCost(costKrw: number | null): string {
  if (costKrw === null) return "단가 모름";
  if (costKrw < 100) return "100원 미만";
  return `약 ${(Math.round(costKrw / 10) * 10).toLocaleString("ko-KR")}원`;
}

/** 확인 단계의 한 줄 — 「새로 채점할 n명 · 예상 비용」. */
export function estimateLine(estimate: QualityEstimate): string {
  return `새로 채점할 ${estimate.new_count}명 · ${formatQualityCost(estimate.cost_krw)}`;
}

/** 참여자 본인 줄 — 「완성도 순위 k등 / N명」. */
export function myRankLine(rank: number, total: number): string {
  return `완성도 순위 ${rank}등 / ${total}명`;
}
