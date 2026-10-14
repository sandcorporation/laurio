// 1200px 틀 안의 두 열 (#637, 시안 v2) — 왼쪽은 본문, 오른쪽은 300px 로 스크롤을 따라온다.
//
// 틀이 1200px 이라 뷰포트가 1200px 이상일 때만 두 열이고, 그보다 좁으면 한 열로 쌓인다
// (본문이 먼저, 오른쪽 열이 그 아래). 옆 여백에 고정하던 1840px 기준은 쓰지 않는다.
// 문제 편집·새 문제가 쓰고, 제출 현황(#638)·참여자 제출(#640)도 같은 틀이다.
import type { ReactNode } from "react";

export function TwoColumnFrame({
  main,
  side,
  sideTestId,
}: {
  main: ReactNode;
  side: ReactNode;
  sideTestId?: string;
}) {
  return (
    <div className="grid grid-cols-1 gap-5 min-[1200px]:grid-cols-[minmax(0,1fr)_300px] min-[1200px]:items-start">
      <div className="flex min-w-0 flex-col gap-5">{main}</div>
      <aside
        data-testid={sideTestId}
        className="flex min-w-0 flex-col gap-5 min-[1200px]:sticky min-[1200px]:top-6 min-[1200px]:max-h-[calc(100vh-3rem)] min-[1200px]:overflow-y-auto"
      >
        {side}
      </aside>
    </div>
  );
}
