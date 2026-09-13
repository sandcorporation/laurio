// 공개 앱 화면이 공유하는 조각(#367) — 강의실의 `app/components/ui.tsx`(#298)를
// 기준으로 같은 이름·같은 모양을 낸다. 두 앱을 한 브랜드로 되돌리는 작업(#358)의
// 일부다.
//
// **워크스페이스 패키지로 승격하지 않는다.** 멤버가 늘면 손으로 관리되는 목록
// 셋(Dockerfile 둘·compose 볼륨)을 같이 고쳐야 하고 로컬 게이트가 그것을 보지
// 못한다 — 공개 앱 안에 둔 채 강의실과 갈라지면 브랜드 검사가 잡는다.
//
// **클래스 계산은 `lib/ui/classnames.ts`에 있다.** 이 저장소의 순수 함수
// 시임(ADR-0026)이 react 임포트를 거부하므로, 단위 테스트가 고정할 수 있는
// 부분(톤·크기별 클래스 문자열)과 JSX 부분을 이 경계에서 가른다.
//
// **이 티켓은 조각을 세우기만 한다.** 기존 화면을 이 조각으로 옮기는 것은
// 다음 티켓들(#368·#369)의 몫이다.
import { createElement } from "react";
import type { ReactNode } from "react";

import {
  INPUT_CLASS,
  badgeClass,
  buttonClass,
  noteClass,
  type BadgeTone,
  type ButtonSize,
  type ButtonTone,
  type NoteTone,
} from "@/lib/ui/classnames";

export { buttonClass, INPUT_CLASS };
export type { BadgeTone, ButtonSize, ButtonTone, NoteTone };

/** 화면 한 장의 바깥 틀 — 폭과 여백을 여기서만 정한다. */
export function PageShell({ children }: { children: ReactNode }) {
  return <main className="mx-auto w-full max-w-3xl px-6 py-10">{children}</main>;
}

/** 화면 머리 — 눈썹(작은 위치 표시)·제목·한 줄 설명, 그리고 오른쪽 행동. */
export function PageHeader({
  eyebrow,
  title,
  titleTestId,
  description,
  actions,
  headingLevel = "h1",
}: {
  eyebrow?: string;
  title: string;
  /** 화면의 제목은 `h1` 하나여야 한다 — 테스트가 잡을 자리를 여기로 준다. */
  titleTestId?: string;
  description?: ReactNode;
  actions?: ReactNode;
  /** 이 헤더가 화면의 `h1`이 아니라 다른 화면 안에 포갠 자리일 때 `"h2"`를
   *  준다 — 그 화면의 진짜 `h1`이 따로 있으므로 여기서 또 `h1`을 내면 접근성
   *  트리의 제목 목록이 둘로 갈린다(강의실의 같은 규칙, #325). */
  headingLevel?: "h1" | "h2";
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        {eyebrow ? <div className="text-xs tracking-wide text-ink/45">{eyebrow}</div> : null}
        {createElement(
          headingLevel,
          { className: "text-2xl font-semibold tracking-tight", "data-testid": titleTestId },
          title,
        )}
        {description ? <p className="text-sm leading-relaxed text-ink/60">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center justify-end gap-2">{actions}</div> : null}
    </div>
  );
}

/** 종이 위에 뜬 면. 그림자가 아니라 괘선으로 뜬다. */
export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`border border-rule bg-surface ${className}`}>{children}</div>;
}

export function CardHeader({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 border-b border-rule px-4 py-3">
      <h2 className="text-base font-semibold tracking-tight">{title}</h2>
      {hint ? <span className="text-xs text-ink/45">{hint}</span> : null}
    </div>
  );
}

/** 카드 밖에 홀로 서는 섹션 머리글 — 제목만 `<h2>`에 담고, 옆 텍스트는 형제
 *  `<span>`으로 둔다(강의실의 같은 규칙, #321) — 화면 낭독기의 머리글 목록에
 *  문장이 머리글인 척 끼어들지 않게 한다. */
export function SectionHeading({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="text-base font-semibold">
      <h2 className="inline">{title}</h2>
      {hint ? <span className="font-normal text-ink/45"> {hint}</span> : null}
    </div>
  );
}

/** 아직 아무것도 없을 때. 「0」이 아니라 「아직 없다」라고 말한다. */
export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="px-4 py-10 text-center text-sm text-ink/45">{children}</div>;
}

/** 상태 표시. 셋뿐이다 — 이 브랜드의 액센트가 둘이기 때문이다. */
export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={badgeClass(tone)}>{children}</span>;
}

/** 숫자는 등폭으로 — 자릿수가 흔들리면 표가 읽히지 않는다. */
export function Num({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono ${className}`}>{children}</span>;
}

export function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="text-xs text-ink/60">{children}</span>;
}

/** 오류는 붉게, 그러나 배경을 채우지 않는다 — 이 브랜드는 면을 칠하지 않는다. */
export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="text-sm leading-relaxed text-attention">
      {children}
    </p>
  );
}

/** 설명·주의를 담는 띠. 괘선 하나로 본문과 구별한다. */
export function Note({ children, tone = "neutral" }: { children: ReactNode; tone?: NoteTone }) {
  return <div className={noteClass(tone)}>{children}</div>;
}
