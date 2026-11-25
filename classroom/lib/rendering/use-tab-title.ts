"use client";

// 대상 화면에서 이 훅 하나로 탭 제목을 맞춘다(#393) — 데이터가 클라이언트에서
// 도착하므로 `<head>` 메타데이터가 아니라 `document.title`을 직접 쓴다. 조립은
// `buildClassroomTabTitle`(순수 함수)이 전담하고, 이 훅은 그 결과를 반영만 한다.
import { useEffect } from "react";

import { buildClassroomTabTitle, type ClassroomTabTitleParts } from "./tab-title";

export function useClassroomTabTitle(parts: ClassroomTabTitleParts): void {
  const { screenName, className, problemTitle } = parts;

  useEffect(() => {
    const title = buildClassroomTabTitle({ screenName, className, problemTitle });
    // 같은 화면 안에서 주소만 바뀌어도(`?tab=`) Next 가 루트 레이아웃의 제목을 다시 써 넣는데, 위 세
    // 값은 그대로라 이 효과는 다시 돌지 않는다(#1400). 화면이 떠 있는 동안 지켜본다 — Next 의 스트리밍
    // metadata 는 `<title>` 을 `<body>` 에 넣기도 해서 `<head>` 가 아니라 문서 전체다.
    const apply = () => {
      if (document.title !== title) document.title = title;
    };
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
  }, [screenName, className, problemTitle]);
}
