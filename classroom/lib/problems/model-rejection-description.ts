// 거부된 모델의 select 를 「모델 거부」 배지 묶음에 묶는다(#1436-8) — 화면 낭독기가 select 에서 거부 사실을 읽는다.
export function modelRejectionNoteId(testIdPrefix: string): string {
  return `${testIdPrefix}-model-rejected-note`;
}

export function modelSelectDescribedBy(testIdPrefix: string, rejected: boolean): string | undefined {
  return rejected ? modelRejectionNoteId(testIdPrefix) : undefined;
}
