"use client";

// ContestView 를 브라우저가 알린다 (#109, 부모 #105, `CONTEXT.md`의
// `ContestView` 정의, ADR-0015).
//
// 부모(`page.tsx`)는 서버 컴포넌트로 남는다 — 이 파일만 클라이언트 컴포넌트를
// 선언해 마운트된 뒤 한 번 `POST /api/backend/contests/{id}/views`를 쏜다.
// 서버 렌더(`fetchContest`가 부르는 `GET /contests/{id}`)는 이 요청을 전혀
// 모른다 — 렌더는 몇 번을 다시 그려도 조회수를 바꾸지 않는다. 미리
// 불러오기·크롤러는 이 컴포넌트를 마운트하지 않으므로(JS를 실행하지 않거나
// 페이지를 실제로 열지 않는다) 세지 않는다 — 그 손실은 받아들이기로 한
// 것이다(#105 "알아 둘 것").
//
// 판정(날짜별 중복 제거·Sponsor 자기 조회 배제·방문자 식별)은 전부 백엔드
// (`contests.view_tracking`)가 한다 — 이 컴포넌트는 신호를 보내기만 하고,
// 응답도 읽지 않는다(조회수는 Sponsor 전용이라 이 공개 화면에 실릴 값이
// 애초에 없다).
import { useEffect } from "react";

export function ContestViewBeacon({ contestId }: { contestId: number }) {
  useEffect(() => {
    // 조회 집계는 화면 동작에 영향을 주지 않는 부가 신호다 — 실패해도
    // 사용자에게 보여줄 것이 없고, 재시도하지도 않는다. 이번 방문 하나가
    // 안 잡히는 손실은 JS를 끈 방문자를 세지 않기로 한 것과 같은 급이다.
    fetch(`/api/backend/contests/${contestId}/views`, { method: "POST" }).catch(() => {});
  }, [contestId]);

  return null;
}
