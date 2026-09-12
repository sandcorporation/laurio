// 클래스 상세에서 채점 키 없음 배너(#347)를 띄울지 — 보관된 클래스는 새
// 제출을 받지 않으므로(docs/features/classroom.md 「보관」절) 키가 없어도
// "참여자가 제출해도 채점되지 않습니다"는 일어날 수 없는 일이다(#352).
export function shouldShowMissingScoringKeyBanner(classroom: {
  archived: boolean;
  has_openai_key: boolean;
}): boolean {
  return !classroom.archived && !classroom.has_openai_key;
}
