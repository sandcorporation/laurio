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

export const EVIDENCE_KINDS: { value: EvidenceIn["kind"]; label: string }[] = [
  { value: "video_timestamp", label: "영상 타임스탬프" },
  { value: "screenshot", label: "스크린샷" },
  { value: "demo_path", label: "데모 내 경로" },
  { value: "source_location", label: "소스 위치" },
];
