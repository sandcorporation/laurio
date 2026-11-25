// 거부된 모델의 select 를 「모델 거부」 배지 묶음에 묶는다(#1436-8) — 화면 낭독기가 select 에서 거부 사실을 읽는다.
export function modelRejectionNoteId(testIdPrefix: string): string {
  return `${testIdPrefix}-model-rejected-note`;
}

export function modelSelectDescribedBy(testIdPrefix: string, rejected: boolean): string | undefined {
  return rejected ? modelRejectionBadgeId(testIdPrefix) : undefined;
}

// 거부된 현재 값 줄(클래스 설정 「기본 모델」, #1441-2)을 라디오 묶음의 설명으로 묶는다.
export const DEFAULT_MODEL_UNAVAILABLE_ID = "class-default-model-unavailable";

export function defaultModelGroupDescribedBy(unavailable: boolean): string | undefined {
  return unavailable ? DEFAULT_MODEL_UNAVAILABLE_ID : undefined;
}

// 거부 배지만 가리키는 id(#1441-11) — 「이 모델로 다시 시도」 단추 글자는 설명에 넣지 않는다.
export function modelRejectionBadgeId(testIdPrefix: string): string {
  return `${testIdPrefix}-model-rejected-badge`;
}
