// 파비콘 — 주의색 타일에 종이색 획·노드(#391 Implementation Decisions
// 「파비콘·아이콘」) — 공개 앱·강의실의 잉크 타일과 일부러 다르다. 운영자가
// 탭 여러 개 사이에서 실수로 조작하지 않도록 한눈에 구별하기 위해서다(#391
// user story 3).
//
// 이 앱은 Tailwind·`app/tokens.css`를 쓰지 않으므로(운영자 앱은 브랜드 가드
// 대상이 아니다, `frontend/lib/ui/brand-guard.test.ts`) 색은 리터럴 hex다 —
// `frontend/app/tokens.css`의 `--color-attention`·`--color-paper`와 같은 값을
// 손으로 맞춘다.
import { ImageResponse } from "next/og";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

const ATTENTION = "#c4442b";
const PAPER = "#f5f3ec";

export default function Icon() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", background: ATTENTION }}>
        <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
          <path
            d="M23.07 8.93 A10 10 0 1 0 23.07 23.07"
            stroke={PAPER}
            strokeWidth={3.6}
            strokeLinecap="round"
          />
          <circle cx="23.07" cy="23.07" r="3.9" fill={PAPER} />
        </svg>
      </div>
    ),
    { ...size },
  );
}
