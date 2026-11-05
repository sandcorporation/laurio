// AI grill 개최 화면(FE-12, #37)이 쓰는 타입 — @codemit/bff-client/schema(FE-03 #28, 패키지로 이사 #146)가
// 백엔드 OpenAPI 스키마에서 생성한 것만 재노출한다. Contest·Verification 타입은
// 이미 lib/submissions/types.ts(FE-10, #35)가 재노출해 뒀으므로 여기서 다시
// 선언하지 않고 그대로 가져다 쓴다 — 같은 백엔드 스키마를 두 곳에서 각자
// 손으로 베끼면 한쪽만 갱신되는 드리프트가 생긴다.
import type { components } from "@codemit/bff-client/schema";

export type { ContestDetail, VerificationStatusOut } from "@/lib/submissions/types";

export type Category = components["schemas"]["CategoryOut"];
export type DeliverableType = components["schemas"]["DeliverableTypeOut"];
export type RequirementOut = components["schemas"]["RequirementOut"];
export type RequirementChatTurnOut = components["schemas"]["RequirementChatTurnOut"];

export type RequirementGrade = "required" | "optional" | "bonus";

/** 요건 행 고치기 — 문구·등급·숨김은 `PATCH …/requirements/{id}`, 배점(1~10)은 `PATCH …/requirements/{id}/points`(#904). */
export type RequirementPatch = { text?: string; grade?: RequirementGrade; points?: number; hidden?: boolean };

/** 숨은 항목 스위치(#906)를 켤 수 없는가 — 유료 공모전은 필수 항목을 숨길 수 없다(서버도 422). */
export function hiddenLocked(isFree: boolean, grade: RequirementGrade): boolean {
  return !isFree && grade === "required";
}

// contests/schemas.py `_VALID_GRADES`와 같은 값 집합 — 백엔드가 등급 문자열을
// 검증하는 기준을 프론트 셀렉트 옵션에도 그대로 옮겨 적는다.
export const REQUIREMENT_GRADES: { value: RequirementGrade; label: string }[] = [
  { value: "required", label: "필수" },
  { value: "optional", label: "선택" },
  // 가산(#905) — AI 가 매기지 않고 마감 뒤 개최자가 0~5 로 매긴다.
  { value: "bonus", label: "가산 · 마감 뒤 개최자가 매김" },
];

/** 등급 문자열 → 배지 글자. 모르는 값은 「선택」(필수가 아니다). */
export function requirementGradeLabel(grade: string): string {
  return REQUIREMENT_GRADE_LABEL[grade as RequirementGrade] ?? "선택";
}

/** 등급 배지 글자 — 필수·선택·가산. */
export const REQUIREMENT_GRADE_LABEL: Record<RequirementGrade, string> = {
  required: "필수",
  optional: "선택",
  bonus: "가산",
};

// contests/schemas.py RequirementIn/RequirementCreateIn/RequirementUpdateIn의
// text: Field(max_length=500)과 같다 — 서버가 어차피 자르거나 422로 거부할
// 값을 보내지 않도록 입력 단계에서부터 맞춘다.
export const REQUIREMENT_TEXT_MAX_LENGTH = 500;

// contests/schemas.py RequirementChatMessageIn.message: Field(max_length=2000)과
// 같다.
export const CHAT_MESSAGE_MAX_LENGTH = 2000;

// contests/api.py `_MAX_CHAT_HISTORY_TURNS`와 같다 — 이 턴 수(sponsor+assistant
// 메시지 총합)에 도달하면 서버가 422로 거부하므로, 그 전에 입력을 막아 사용자가
// 이유 없는 실패를 겪지 않게 한다.
export const CHAT_MAX_HISTORY_TURNS = 200;
