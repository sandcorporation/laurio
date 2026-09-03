// Submission 제출 폼(FE-10, #35)이 쓰는 타입은 손으로 다시 적지 않는다 —
// lib/api/schema.gen.ts(FE-03, #28)가 백엔드 OpenAPI 스키마 전체(공개+인증
// 엔드포인트 모두)에서 이미 생성해뒀다. 여기서는 그 타입만 재노출한다 — 이
// 파일이 실제로 백엔드를 부르지는 않는다(BFF 프록시를 거치는 raw fetch는
// app/console/contests/[contestId]/submit/page.tsx에 있다). lib/api/client.ts의
// backendClient(서버 전용, 공개 표면만)와 달리 이 타입들은 인증 구역
// 클라이언트 컴포넌트에서 그대로 import해도 안전하다 — 타입은 런타임에
// 아무 것도 하지 않는다.
import type { components } from "@/lib/api/schema.gen";

export type ContestDetail = components["schemas"]["ContestOut"];
export type RequirementOut = components["schemas"]["RequirementOut"];
export type SubmissionOut = components["schemas"]["SubmissionOut"];
export type SubmissionIn = components["schemas"]["SubmissionIn"];
export type RequirementResponseOut = components["schemas"]["RequirementResponseOut"];
export type RequirementResponseIn = components["schemas"]["RequirementResponseIn"];
export type EvidenceOut = components["schemas"]["EvidenceOut"];
export type EvidenceIn = components["schemas"]["EvidenceIn"];
export type VerificationStatusOut = components["schemas"]["VerificationStatusOut"];

// 심사 비교 화면(FE-11, #36)이 쓰는 타입. ContestComparisonOut(및 그 하위
// 타입)은 백엔드 스키마 자체에 source_object_key·test_account·Score 필드가
// 없다(submissions/schemas.py 상단 주석 참고) — "존재하지만 안 보임"이 아니라
// 애초에 필드가 없으므로, 이 타입을 그대로 클라이언트 컴포넌트 props로 넘겨도
// 하이드레이션 페이로드에 소스·점수가 실릴 수 없다.
export type ContestComparisonOut = components["schemas"]["ContestComparisonOut"];
export type RequirementComparisonOut = components["schemas"]["RequirementComparisonOut"];
export type ComparisonEntryOut = components["schemas"]["ComparisonEntryOut"];
export type ComparisonSubmissionOut = components["schemas"]["ComparisonSubmissionOut"];
export type AwardIn = components["schemas"]["AwardIn"];
export type AwardOut = components["schemas"]["AwardOut"];

// Sponsor 지표 화면(#107, 부모 #105)이 쓰는 타입. `ContestMetricsOut` 에도 다른
// 비교 화면 타입들과 같은 이유로 developer_id·submission_id·Score 필드가 없다 —
// 백엔드 스키마(submissions/schemas.py) 자체에 없으므로, 이 타입을 그대로
// 클라이언트 컴포넌트 props 로 넘겨도 개별 참가자나 점수가 새어나갈 수 없다.
export type ContestMetricsOut = components["schemas"]["ContestMetricsOut"];
export type DailyParticipationOut = components["schemas"]["DailyParticipationOut"];
export type RequirementFulfillmentOut = components["schemas"]["RequirementFulfillmentOut"];
export type CompletionDistributionOut = components["schemas"]["CompletionDistributionOut"];
// #109, 부모 #105 — 조회수·전환율. `view_count`는 캐시에서 온 집계 하나뿐이고
// 방문자 식별자는 이 타입에도 없다.
export type ViewMetricsOut = components["schemas"]["ViewMetricsOut"];

export const EVIDENCE_KINDS: { value: EvidenceIn["kind"]; label: string }[] = [
  { value: "video_timestamp", label: "영상 타임스탬프" },
  { value: "screenshot", label: "스크린샷" },
  { value: "demo_path", label: "데모 내 경로" },
  { value: "source_location", label: "소스 위치" },
];
