// 강의실 화면이 공유하는 조각 (#298).
//
// **시안(`docs/design/classroom/`)이 정한 규칙을 여기 한 번만 적는다** — 종이 위에
// 뜬 면은 `surface`, 면과 면은 **괘선**으로 가르고 **그림자는 쓰지 않으며**, 모서리는
// 각지다(토큰의 radius 가 0–2px). 화면마다 같은 유틸리티 문자열을 베끼면 한 곳을
// 고칠 때 나머지가 남는다.
//
// 리터럴 hex 는 여기에도 없다 — 전부 `app/tokens.css` 의 `@theme` 가 만든
// 유틸리티다(`bg-paper`·`text-ink`·`border-rule`·`text-attention`·`text-verified`).
import { createElement } from "react";
import type { ReactNode } from "react";

/** 화면 한 장의 바깥 틀 — 폭과 여백을 여기서만 정한다. */
export function PageShell({ children }: { children: ReactNode }) {
  return <main className="mx-auto w-full max-w-[1200px] px-6 py-8">{children}</main>;
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
  /** 화면의 제목은 `h1` 하나여야 한다 — 테스트가 잡을 자리를 여기로 준다.
   *  따로 `sr-only` 제목을 덧대면 h1 이 둘이 되어 읽는 순서가 무너진다
   *  (브라우저로 걷다가 실제로 세 화면에서 그 상태를 봤다). */
  titleTestId?: string;
  description?: ReactNode;
  actions?: ReactNode;
  /** 이 헤더가 화면의 `h1`이 아니라 다른 화면 안에 포갠 자리(예: 문제
   *  만들기/편집의 「미리보기」 탭이 참여자 화면을 그대로 보여주는 자리,
   *  #325)일 때 `"h2"`를 준다 — 그 화면의 진짜 `h1`이 따로 있으므로 여기서
   *  또 `h1`을 내면 위 규칙이 깨진다. */
  headingLevel?: "h1" | "h2";
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        {eyebrow ? (
          <div className="text-[11px] tracking-[0.08em] text-ink/45">{eyebrow}</div>
        ) : null}
        {createElement(
          headingLevel,
          { className: "text-[22px] font-semibold tracking-[-0.01em]", "data-testid": titleTestId },
          title,
        )}
        {description ? (
          <p className="text-[13px] leading-relaxed text-ink/60">{description}</p>
        ) : null}
      </div>
      {/* actions 는 wrap 한다(#336) — 버튼이 넷까지 늘어난 화면(클래스 상세)에서
          390px 폭이면 한 줄에 다 안 들어간다. shrink 대신 wrap 을 쓰는 이유는
          버튼 텍스트가 whitespace-nowrap 이라 눌러 찌그러뜨릴 수 없어서다. */}
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
      <h2 className="text-[15px] font-semibold tracking-[-0.005em]">{title}</h2>
      {hint ? <span className="text-[12.5px] text-ink/45">{hint}</span> : null}
    </div>
  );
}

/** 카드 밖에 홀로 서는 섹션 머리글 — 제목만 `<h2>` 에 담고, 옆 텍스트(개수든
 *  문장이든)는 형제 `<span>` 으로 둔다(#321). 화면 낭독기는 머리글 목록을 훑어
 *  건너뛰는데, 부제 문장이 `<h2>` 안에 있으면 그 목록에 문장 하나가 머리글인 척
 *  끼어들어 목록이 못 쓰게 된다 — `title` 만 읽히게 갈라 둔다. */
export function SectionHeading({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="text-[15px] font-semibold">
      <h2 className="inline">{title}</h2>
      {hint ? <span className="font-normal text-ink/45"> {hint}</span> : null}
    </div>
  );
}

/** 아직 아무것도 없을 때. 「0」이 아니라 「아직 없다」라고 말한다. */
export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="px-4 py-10 text-center text-[13.5px] text-ink/45">{children}</div>;
}

const BUTTON_BASE =
  "inline-flex items-center justify-center whitespace-nowrap text-[13.5px] " +
  "transition-colors disabled:cursor-not-allowed disabled:opacity-45";
const BUTTON_TONE = {
  primary: "bg-ink text-paper hover:bg-ink/85",
  secondary: "border border-rule bg-surface text-ink hover:bg-paper",
  danger: "border border-attention bg-surface text-attention hover:bg-attention/5",
  // 되돌릴 수 없는 행위 중, 확인을 이미 거친 최종 실행에만 쓴다(#344) — 입구·한
  // 번에 끝나는 행위는 위 danger(테두리)를 쓴다. 공개 앱의 확정 버튼과 같은
  // bg-attention/text-paper 조합이라 두 앱에서 「채움 = 최종 실행」이 같은 색으로 읽힌다.
  dangerFilled: "bg-attention text-paper hover:bg-attention/85",
} as const;

export type ButtonTone = keyof typeof BUTTON_TONE;

/** 버튼과 링크가 같은 모양을 내도록, 클래스만 돌려준다. */
export function buttonClass(tone: ButtonTone = "secondary", size: "sm" | "md" = "md"): string {
  // sm 은 공개 앱(`frontend/lib/ui/classnames.ts`)과 같은 값이다 — 헤더의 같은
  // 버튼이 두 앱에서 크기가 갈렸었다.
  const pad = size === "sm" ? "px-3 py-1.5 text-xs" : "px-4 py-2";
  return `${BUTTON_BASE} ${BUTTON_TONE[tone]} ${pad}`;
}

/** 상태 표시. 셋뿐이다 — 이 브랜드의 액센트가 둘이기 때문이다. */
export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "attention" | "verified";
  children: ReactNode;
}) {
  const cls = {
    neutral: "border-rule text-ink/60",
    attention: "border-attention text-attention",
    verified: "border-verified text-verified",
  }[tone];
  return (
    // `shrink-0 whitespace-nowrap` — 배지는 flex 안에서 눌리면 안 된다(2026-09-16).
    // 좁은 칸(문제 편집 오른쪽 300px 카드)에서 「내려짐」이 한 글자씩 세로로 쪼개져
    // 나왔다: `inline-block` 은 flex 자식으로서 min-content 까지 줄어들고, 그 폭이
    // 한 글자다. 라벨은 짧은 낱말이므로 줄바꿈할 이유가 애초에 없다.
    <span
      className={`inline-block shrink-0 border px-2 py-0.5 text-[11px] leading-tight whitespace-nowrap ${cls}`}
    >
      {children}
    </span>
  );
}

/** 숫자는 등폭으로 — 자릿수가 흔들리면 표가 읽히지 않는다. */
export function Num({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono ${className}`}>{children}</span>;
}

export function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="text-[12px] text-ink/60">{children}</span>;
}

export const INPUT_CLASS =
  "w-full border border-rule bg-surface px-3 py-2 text-[13.5px] text-ink " +
  "placeholder:text-ink/30 focus:border-ink focus:outline-none";

/** 오류는 붉게, 그러나 배경을 채우지 않는다 — 이 브랜드는 면을 칠하지 않는다. */
export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="text-[13px] leading-relaxed text-attention">
      {children}
    </p>
  );
}

/** 설명·주의를 담는 띠. 괘선 하나로 본문과 구별한다. */
export function Note({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "attention" }) {
  const border = tone === "attention" ? "border-attention" : "border-rule";
  const text = tone === "attention" ? "text-ink/75" : "text-ink/60";
  return (
    <div className={`border ${border} bg-surface px-4 py-3 text-[13px] leading-relaxed ${text}`}>
      {children}
    </div>
  );
}
