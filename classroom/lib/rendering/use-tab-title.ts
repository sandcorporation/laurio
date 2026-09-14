"use client";

// 대상 화면에서 이 훅 하나로 탭 제목을 맞춘다(#393) — 데이터가 클라이언트에서
// 도착하므로 `<head>` 메타데이터가 아니라 `document.title`을 직접 쓴다. 조립은
// `buildClassroomTabTitle`(순수 함수)이 전담하고, 이 훅은 그 결과를 반영만 한다.
import { useEffect } from "react";

import { buildClassroomTabTitle, type ClassroomTabTitleParts } from "./tab-title";

export function useClassroomTabTitle(parts: ClassroomTabTitleParts): void {
  const { screenName, className, problemTitle } = parts;

  useEffect(() => {
    document.title = buildClassroomTabTitle({ screenName, className, problemTitle });
  }, [screenName, className, problemTitle]);
}
