// 제목 붙은 카드 — 폼·이력·안내를 한 모양으로 담는 조각(#424, 부모 #421 「표를
// 공통 조각으로 둔다」와 같은 원칙을 카드에도 적용했다). `page-header.tsx`가
// 화면 전체의 눈썹이라면 이건 화면 안의 구획이다 — 운영팀 알림(폼·약속·이력)과
// 개최 권한(검색·보유 계정·이력)이 함께 쓴다.
import type { ReactNode } from "react";

export function Panel({
  title,
  meta,
  actions,
  children,
}: {
  title: string;
  meta?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="border border-rule bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-[15px] py-3">
        <div className="text-[14px] font-semibold">
          {title}
          {meta && <span className="ml-[9px] text-[12.5px] font-normal text-ink/45">{meta}</span>}
        </div>
        {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
}
