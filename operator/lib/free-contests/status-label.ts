// Contest.Status 의 한글 라벨 — `contests/models.py`의 `Status.choices`와 같은
// 값(공개 앱 `frontend/lib/contest-format.ts`의 FINISHED_STATUS_LABELS와도
// 같은 한글을 쓴다, 다만 그쪽은 공개 앱 패키지라 여기서 import하지 않는다).
const STATUS_LABELS: Record<string, string> = {
  draft: "초안",
  published: "공개",
  closed: "마감",
  awarded: "선정 완료",
  judging_ended: "심사기간 종료",
};

export function freeContestStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}
