// 표를 본문 폭 안에서만 가로로 넘기는 틀(#523). 운영자 앱의 표는 `<table>` 이 아니라
// 고정 너비 열(`w-[…] shrink-0`)과 늘어나는 열(`flex-1`)로 짠 flex 행이라, 좁은
// 화면에서는 고정 열이 줄지 않고 오른쪽으로 삐져나가 **화면 전체**가 옆으로 밀렸다.
//
// 이 틀이 하는 일은 둘이다: 바깥은 `overflow-x-auto` 로 넘침을 자기 안에 가두고,
// 안쪽은 `minWidth` 아래로 줄지 않게 해 늘어나는 열(이름·사유·무엇을)이 0 으로
// 짜부라지지 않게 한다. 본문이 `minWidth` 보다 넓으면(넓은 화면) 아무 일도 하지
// 않는다 — 1440px 화면은 예전과 같다.
//
// `minWidth` 는 표마다 다르다 — 고정 열 너비의 합에 늘어나는 열이 읽힐 만큼을 더한
// 값이다. 테두리·바탕을 두른 바깥 상자(와 그 data-testid)는 그대로 두고 그 안쪽을
// 이 틀로 감싼다. 넓은 화면의 본문(1440 - 내비 208 - 여백 64 = 1168px)보다 크게 잡지 않는다.
//
// 첫 열을 붙여 두지(sticky) 않았다 — 운영자 표는 행마다 맨 앞 열(이름·날짜)이 짧아
// 넘겨도 한 화면에 행의 뜻이 남고, 붙인 열은 줄무늬·누름 배경을 따로 칠해야 해
// 행 모양이 갈라진다. 필요해지면 화면마다 판단한다(#523).
import type { ReactNode } from "react";

export function TableScroll({ minWidth, children }: { minWidth: number; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <div style={{ minWidth }}>{children}</div>
    </div>
  );
}
