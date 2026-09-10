"use client";

// 마감을 넘는 순간 제출물을 한 번 다시 불러온다 (#247, #248).
//
// **판정기는 서버 하나뿐이어야 한다.** `next_action`(`submissions.
// participation.next_action_for`)이 이미 "지금 무엇을 해야/기다려야 하는가"를
// 답하는데, 화면이 `now >= deadlineAt`을 직접 비교해 "마감됐다"를 스스로
// 판정하면 그 판정기가 하나 더 생긴다. 그러면 나중에 새 상태(채점 대기·심사
// 중 등)가 생겨도 이 화면은 조용히 낡은 것을 말하게 된다.
//
// 그래도 시각 비교를 완전히 버리지는 않는다 — `next_action`은 화면이 처음
// 불러온 시점의 스냅샷이라, 편집 가능한 채로 화면을 켜 둔 사이 마감을 넘기면
// 다시 묻기 전까지는 여전히 "수정할 수 있습니다"로 보인다. 이 훅이 하는 일은
// **판정이 아니라 타이밍**이다 — 시계가 마감을 넘는 그 순간 제출물만 한 번
// 다시 불러와 `next_action`을 갱신한다. 무엇을 보여줄지는 여전히 서버가 답한
// 값이다.
//
// 공모전 제출 화면(#247)과 과제 제출자 화면(#248)이 원래 이 로직을 각자
// 손으로 들고 있었다 — 판정기를 하나로 유지하자는 것이 이 로직 자체의
// 존재 이유인데, 그 로직이 두 벌이면 한쪽만 고쳐졌을 때 두 화면이 조용히
// 갈린다. 그래서 여기 하나로 모은다.
import { useEffect, useRef } from "react";

import { bffClient } from "@/lib/bff/client";
import type { SubmissionOut } from "@/lib/submissions/types";

export function useDeadlineRefetch({
  now,
  deadlineAt,
  canEdit,
  hasSubmission,
  path,
  onResult,
}: {
  /** 매초 갱신되는 현재 시각(`Date.now()`) — 언제 다시 물을지 고르는 타이밍일
   * 뿐 판정에는 쓰지 않는다. */
  now: number;
  deadlineAt: number | null;
  /** 이미 편집 불가라면(`next_action !== "can_edit_submission"`) 다시 물을
   * 이유가 없다 — 그 값을 갱신하는 것이 이 훅의 유일한 목적이다. */
  canEdit: boolean;
  /** 아직 제출물이 없으면 다시 물을 대상 자체가 없다. */
  hasSubmission: boolean;
  /** `null`이면(예: 아직 조회 준비가 안 됐다) 이 틱을 건너뛴다. */
  path: string | null;
  /** 다시 불러온 제출물을 화면 상태에 반영한다 — 두 화면이 상태를 담는
   * 그릇(`load.submission` vs `submission`)이 달라 호출부가 직접 반영한다. */
  onResult: (submission: SubmissionOut) => void;
}) {
  const refetchedRef = useRef(false);

  useEffect(() => {
    if (deadlineAt === null || !canEdit || !hasSubmission || path === null) return;
    if (now < deadlineAt) {
      refetchedRef.current = false;
      return;
    }
    if (refetchedRef.current) return;
    refetchedRef.current = true;

    bffClient.get<SubmissionOut>(path).then((result) => {
      if (result.ok) onResult(result.data);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `onResult`는 매
    // 렌더 새로 만들어지는 클로저다. `now`가 1초마다 갈려 이 이펙트가 어차피
    // 매초 다시 도므로 항상 최신 클로저를 쓴다 — deps에 넣으면 그 사실과
    // 무관하게 매 렌더 이펙트가 다시 걸린다.
  }, [now, deadlineAt, canEdit, hasSubmission, path]);
}
