"use client";

// 공개 상세의 제출 CTA가 자기 Contest에는 안 보이게 감춘다 (#164) — 그리고
// 이미 낸 사람에게는 "수정"임을 누르기 전에 드러낸다 (#245).
//
// **이 컴포넌트가 링크 전체를 그린다.** `page.tsx`(서버 컴포넌트)는 직렬화할
// 수 없는 값(함수·JSX 렌더 프롭)을 클라이언트 컴포넌트에 건널 수 없다 —
// 처음에는 `children`을 렌더 프롭으로 받아 부모가 문구를 고르게 했는데,
// RSC 경계를 넘는 순간 "Functions are not valid as a child of Client
// Components"로 그대로 죽었다. 그래서 이 컴포넌트가 `contestId`(직렬화
// 가능한 값) 하나만 받아 조회부터 렌더까지 전부 스스로 한다.
//
// 로그인 여부와 무관하게 항상 보이는 것은 여전히 이 티켓의 핵심이고(로그아웃
// 상태에서 눌러도 미들웨어가 `/login?next=...`로 보낸 뒤 되돌아온다 —
// `app/components/site-header.tsx`의 "공모전 개최" CTA와 정확히 같은 패턴, 새로
// 구현하지 않는다), 그 판단에는 이 컴포넌트가 전혀 관여하지 않는다. 관여하는
// 것은 "숨기는가"와 "무엇을 말하는가" 둘뿐이다.
//
// 소유 여부는 `ContestOut.is_owner`(contests.api._serialize_contest, #164)로,
// 이미 냈는지는 `ContestOut.has_own_submission`(#245, 같은 자리·같은 이유)로만
// 판정한다 — 로그인한 사용자의 id를 화면이 직접 비교하거나, 이 화면이 따로
// `GET .../submissions/me`를 불러 재판정하지 않는다. 그럴 수도 없다: 공개 상세
// SSR(`lib/api/client.ts`)은 ADR-0015가 그은 경계대로 Authorization을 보내지
// 않는 공개 표면 전용이라, sponsor 식별자도 제출 여부도 서버 렌더 페이로드에
// 없다. 그래서 이 컴포넌트가 마운트된 뒤 BFF 프록시를 거쳐 **같은
// 엔드포인트**(`GET /contests/{id}`)를 인증 구역 클라이언트로 다시 불러 두
// 값을 함께 읽는다 — 로그인 상태면 이번에는 실제 값이 온다.
//
// 그 조회는 익명 방문자에게도 안전하다: `/api/contests/{id}`는 auth=None이라
// BFF 프록시가 Authorization 없이도 그대로 통과시킨다(forwardToBackend 주석) —
// 401이 나지 않으므로 `bffClient`의 로그인 리다이렉트가 이 마운트만으로 튀는
// 일은 없다. 그래서 기본값은 항상 "보인다·제출 문구"이고, 조회가 끝나 owner로
// 확인된 순간에만 지운다 — 확인 전에 숨겨 두면 절대다수인 비소유자에게
// 불필요한 깜빡임만 남긴다.
import { useEffect, useState } from "react";
import Link from "next/link";

import { bffClient } from "@/lib/bff/client";
import { buttonClass } from "@/lib/ui/classnames";
import type { ContestDetail } from "@/lib/submissions/types";

export function SubmitCta({ contestId }: { contestId: number }) {
  const [state, setState] = useState<{ isOwner: boolean; hasOwnSubmission: boolean }>({
    isOwner: false,
    hasOwnSubmission: false,
  });

  useEffect(() => {
    let cancelled = false;
    bffClient.get<ContestDetail>(`/api/backend/contests/${contestId}`).then((res) => {
      if (!cancelled && res.ok) {
        setState({ isOwner: res.data.is_owner, hasOwnSubmission: res.data.has_own_submission });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [contestId]);

  if (state.isOwner) return null;

  return (
    <Link href={`/console/contests/${contestId}/submit`} data-testid="submit-cta-link" className={buttonClass("primary")}>
      {state.hasOwnSubmission ? "제출물 수정하러 가기" : "제출하러 가기"}
    </Link>
  );
}
