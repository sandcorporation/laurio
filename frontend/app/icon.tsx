// 파비콘 — 잉크 타일 위에 종이색 획, 통과 초록 노드(#391 Implementation
// Decisions 「파비콘·아이콘」). Next 의 아이콘 파일 컨벤션(`app/icon.tsx`)이
// 이 라우트를 자동으로 `<link rel="icon">`에 연결한다.
//
// **원본은 이 파일이다.** `classroom/app/icon.tsx`는 복사본이고, 두 파일이
// 갈리면 `classroom/lib/design/logo-mark.test.ts`가 잡는다(#298 과 같은 방식).
// 운영자 앱(`operator/app/icon.tsx`)은 주의색 타일로 일부러 다르므로 이 짝에
// 들지 않는다.
//
// satori(`next/og`)는 Tailwind 를 읽지 않고 인라인 스타일만 그린다 — 그래서
// 색은 `app/tokens.css` 의 리터럴 hex 를 그대로 옮긴다. 토큰이 바뀌면 이
// 파일도 손으로 맞춘다(부모 파일 `logo-mark.tsx` 와 달리 CSS 변수를 못 쓴다).
import { ImageResponse } from "next/og";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

const INK = "#17160f";
const PAPER = "#f5f3ec";
const VERIFIED = "#2e6a4c";

export default function Icon() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", background: INK }}>
        <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
          <path
            d="M23.07 8.93 A10 10 0 1 0 23.07 23.07"
            stroke={PAPER}
            strokeWidth={3.6}
            strokeLinecap="round"
          />
          <circle cx="23.07" cy="23.07" r="3.9" fill={VERIFIED} />
        </svg>
      </div>
    ),
    { ...size },
  );
}
