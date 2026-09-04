"use client";

// 공개 상세의 "제출하러 가기" CTA가 자기 Contest에는 안 보이게 감춘다 (#164).
//
// **부모(`page.tsx`)가 먼저 링크를 그린다** — 이 컴포넌트의 `children`이 그
// 링크다. 로그인 여부와 무관하게 항상 보이는 것이 이 티켓의 핵심이고(로그아웃
// 상태에서 눌러도 미들웨어가 `/login?next=...`로 보낸 뒤 되돌아온다 —
// `app/components/site-header.tsx`의 "공모전 개최" CTA와 정확히 같은 패턴, 새로
// 구현하지 않는다), 그 판단에는 이 클라이언트 컴포넌트가 전혀 관여하지 않는다.
//
// 이 컴포넌트가 더하는 것은 "자기 것이면 숨긴다" 하나뿐이다. 소유 여부는
// `ContestOut.is_owner`(contests.api._serialize_contest, #164)로만 판정한다 —
// 로그인한 사용자의 id와 Contest의 sponsor id를 화면이 직접 비교하지 않는다.
// 그럴 수도 없다: 공개 상세 SSR(`lib/api/client.ts`)은 ADR-0015가 그은 경계대로
// Authorization을 보내지 않는 공개 표면 전용이라, sponsor 식별자 자체가 서버
// 렌더 페이로드에 없다. 그래서 이 컴포넌트가 마운트된 뒤 BFF 프록시를 거쳐
// **같은 엔드포인트**(`GET /contests/{id}`)를 인증 구역 클라이언트로 다시
// 불러 `is_owner`를 읽는다 — 로그인 상태면 이번에는 실제 값이 온다.
//
// 그 조회는 익명 방문자에게도 안전하다: `/api/contests/{id}`는 auth=None이라
// BFF 프록시가 Authorization 없이도 그대로 통과시킨다(forwardToBackend 주석) —
// 401이 나지 않으므로 `bffClient`의 로그인 리다이렉트가 이 마운트만으로 튀는
// 일은 없다. 그래서 기본값은 항상 "보인다"이고, 조회가 끝나 owner로 확인된
// 순간에만 지운다 — 확인 전에 숨겨 두면 절대다수인 비소유자에게 불필요한
// 깜빡임만 남긴다.
import { useEffect, useState } from "react";

import { bffClient } from "@/lib/bff/client";
import type { ContestDetail } from "@/lib/submissions/types";

export function HideIfOwnContest({
  contestId,
  children,
}: {
  contestId: number;
  children: React.ReactNode;
}) {
  const [isOwnContest, setIsOwnContest] = useState(false);

  useEffect(() => {
    let cancelled = false;
    bffClient.get<ContestDetail>(`/api/backend/contests/${contestId}`).then((res) => {
      if (!cancelled && res.ok && res.data.is_owner) setIsOwnContest(true);
    });
    return () => {
      cancelled = true;
    };
  }, [contestId]);

  if (isOwnContest) return null;
  return <>{children}</>;
}
