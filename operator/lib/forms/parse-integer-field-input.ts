// 정수 입력칸을 서버로 보낼 값으로 해석한다(코드리뷰 지적).
//
// **`Number("")`는 NaN이 아니라 0이다.** trim() 뒤 빈 문자열을 그대로
// `Number()`에 넘기면 "사용자가 입력칸을 비웠다"가 조용히 "0으로 바꿨다"로
// 둔갑한다. 정책값·DeliverableType 최소 제안 상금처럼 0이 그 자체로 유효한
// 값인 필드에서는 이게 특히 위험하다 — 서버 경계(예: 0~9000) 안에 들어와
// 그대로 200이 돌아온다. 빈 칸으로 수수료율이 조용히 0%가 되거나, 최소
// 제안 상금이 조용히 0원이 되는 사고다.
//
// 이 함정이 정책 화면(policy-editor.tsx)과 DeliverableType 화면
// (type-row.tsx·create-type-form.tsx) 세 곳에서 각자 따로 막힐 뻔했다 —
// 이 저장소는 같은 방어를 두 벌 두었다가 한쪽만 고쳐진 사고를 이미 겪었다
// (OperatorOriginMiddleware의 CSRF 이중화 사고, core/operator_auth.py 참고).
// 그래서 세 곳 모두 이 함수 하나로 판정을 모은다 — 다음에 이런 입력칸이
// 추가돼도 이 함수를 그대로 재사용하면 같은 함정에 다시 빠지지 않는다.
//
// **판별 유니언으로 돌려준다** — `as unknown as number`로 문자열을 number
// 자리에 숨기면(예전 방식) `Number.isNaN(parsed)`가 문자열에 대해 항상
// false를 돌려주는 또 다른 함정에 걸린다(Number.isNaN은 강제 변환을 하지
// 않는다 — 전역 isNaN과 다르다). 호출부는 `valid`로 분기하고, 무효한 값은
// `raw`(빈 문자열이든 숫자 아닌 문자열이든 원본)를 payload에 그대로 실어
// 서버의 요청 검증이 422로 거절하게 한다 — "이 필드는 비어 있으니 안 보낸
// 걸로 치자"고 클라이언트가 조용히 넘어가지 않는다.
export type IntegerFieldParseResult =
  | { valid: true; value: number }
  | { valid: false; raw: string };

export function parseIntegerFieldInput(raw: string): IntegerFieldParseResult {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return { valid: false, raw: trimmed };
  }
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) {
    return { valid: false, raw: trimmed };
  }
  return { valid: true, value: parsed };
}
