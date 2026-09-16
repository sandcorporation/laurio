// 상단 바 — 눈썹(위치)·제목·한 줄 설명·행동 버튼 자리(#422, 부모 #421). 화면마다
// 같은 자리에서 같은 모양으로 말한다. 이 티켓이 옮기는 화면(지급 큐)이 첫
// 사용처이고, 다음 티켓들이 그대로 재사용한다.
import type { ReactNode } from "react";

export function PageHeader({
  crumb,
  title,
  titleTestId,
  description,
  actions,
}: {
  crumb: string;
  title: string;
  /** 화면 제목에 붙일 data-testid — 기존 화면(이의 상세의 `appeal-detail-heading`
   * 등)이 골간으로 옮겨온 뒤에도 같은 주소를 유지해야 하므로(#423) 선택적으로 받는다. */
  titleTestId?: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-end justify-between gap-5 border-b border-rule bg-surface px-8 py-5">
      <div>
        <p className="text-[10.5px] tracking-[0.1em] text-ink/30">{crumb}</p>
        <h1 data-testid={titleTestId} className="mt-1 text-[19px] font-semibold tracking-[-0.01em]">
          {title}
        </h1>
        {description && <p className="mt-1.5 text-[12.5px] text-ink/62">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </div>
  );
}
