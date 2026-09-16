// 공개 앱 공용 UI 조각의 순수 계산부(#367). 강의실의 `app/components/ui.tsx`
// (#298)가 이미 정한 규칙을 그대로 옮긴다 — 종이 위에 뜬 면은 `surface`, 면과
// 면은 **괘선**으로 가르고 **그림자는 쓰지 않으며**, 모서리는 각지다(토큰의
// radius 가 0–2px, 그래서 이 파일은 어디에도 `rounded`류 유틸리티를 쓰지
// 않는다). 두 앱이 같은 이름·같은 모양을 내야 다시 갈라지지 않는다.
//
// **JSX 컴포넌트가 아니라 클래스 문자열만 여기 둔다.** 이 저장소의 순수 함수
// 시임(ADR-0026, `vitest.shared.mts`)이 react 임포트를 이 러너에서 통째로
// 거부하므로, 컴포넌트는 `app/components/ui.tsx`에 두고 이 파일의 함수만
// 가져다 쓴다 — 계약을 단위 테스트로 고정하려면 이 분리가 필요하다.
//
// 리터럴 hex 는 여기에도 없다 — 전부 `app/tokens.css`의 `@theme`가 만든
// 유틸리티다. **이 브랜드의 색은 정확히 여섯**(ink·paper·surface·rule·
// attention·verified)이고 액센트는 정확히 둘(attention·verified)이다 — 이
// 파일이 그 목록 밖의 이름을 부르면 Tailwind 는 조용히 아무 것도 만들지
// 않는다(#366 이 겪은 바로 그 실패). `classnames.test.ts`가 각 톤의 출력
// 문자열을 그대로 고정해 그 실패를 다시 만들지 못하게 막는다.

export type ButtonTone = "primary" | "secondary" | "danger" | "dangerFilled";
export type ButtonSize = "sm" | "md";
export type BadgeTone = "neutral" | "attention" | "verified";
export type NoteTone = "neutral" | "attention";

const BUTTON_BASE =
  "inline-flex items-center justify-center whitespace-nowrap text-sm " +
  "transition-colors disabled:cursor-not-allowed disabled:opacity-50";

const BUTTON_TONE: Record<ButtonTone, string> = {
  primary: "bg-ink text-paper hover:bg-ink/85",
  secondary: "border border-rule bg-surface text-ink hover:bg-paper",
  danger: "border border-attention bg-surface text-attention hover:bg-attention/5",
  // 되돌릴 수 없는 행위 중, 확인을 이미 거친 최종 실행에만 쓴다(강의실의 같은
  // 규칙, #344/#298) — 입구·한 번에 끝나는 행위는 위 danger(테두리)를 쓴다.
  dangerFilled: "bg-attention text-paper hover:bg-attention/85",
};

const BUTTON_SIZE: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2",
};

/** 버튼과 링크가 같은 모양을 내도록, 클래스만 돌려준다. */
export function buttonClass(tone: ButtonTone = "secondary", size: ButtonSize = "md"): string {
  return `${BUTTON_BASE} ${BUTTON_TONE[tone]} ${BUTTON_SIZE[size]}`;
}

const BADGE_TONE: Record<BadgeTone, string> = {
  neutral: "border-rule text-ink/60",
  attention: "border-attention text-attention",
  verified: "border-verified text-verified",
};

/** 상태 표시. 셋뿐이다 — 이 브랜드의 액센트가 둘이기 때문이다. */
// `shrink-0 whitespace-nowrap` — 배지는 flex 안에서 눌리면 안 된다(2026-09-16).
// 강의실의 같은 배지가 좁은 칸에서 「내려짐」을 한 글자씩 세로로 쪼개 냈다:
// `inline-block` 은 flex 자식으로서 min-content(= 한 글자)까지 줄어든다. 여기도
// 같은 구멍이었고, 공개 상세의 「마감된 공모전 — 데모·영상 공개」가 좁은 화면의
// 머리말 줄에서 같은 모양이 될 자리였다. 라벨은 짧은 낱말이라 줄바꿈할 이유가 없다.
export function badgeClass(tone: BadgeTone = "neutral"): string {
  return `inline-block shrink-0 border px-2 py-0.5 text-xs leading-tight whitespace-nowrap ${BADGE_TONE[tone]}`;
}

export const INPUT_CLASS =
  "w-full border border-rule bg-surface px-3 py-2 text-sm text-ink " +
  "placeholder:text-ink/30 focus:border-ink focus:outline-none";

const NOTE_TONE: Record<NoteTone, { border: string; text: string }> = {
  neutral: { border: "border-rule", text: "text-ink/60" },
  attention: { border: "border-attention", text: "text-ink/75" },
};

/** 설명·주의를 담는 띠의 클래스. 면을 칠하지 않는다 — 괘선 하나로 본문과 구별한다. */
export function noteClass(tone: NoteTone = "neutral"): string {
  const { border, text } = NOTE_TONE[tone];
  return `border ${border} bg-surface px-4 py-3 text-sm leading-relaxed ${text}`;
}
