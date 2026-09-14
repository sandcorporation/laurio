// 홈 화면 추가 아이콘 — `app/icon.tsx`와 같은 그림을 더 큰 캔버스(180×180,
// Apple 관례)에 여백을 두어 그린다. iOS 가 씌우는 둥근 마스크에 심볼이 잘리지
// 않게 하기 위해서다(#391 user story 4).
//
// **원본은 이 파일이다.** `classroom/app/apple-icon.tsx`는 복사본이고, 두
// 파일이 갈리면 `classroom/lib/design/logo-mark.test.ts`가 잡는다. 색·도형
// 정의는 `app/icon.tsx` 주석 참고.
import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

const INK = "#17160f";
const PAPER = "#f5f3ec";
const VERIFIED = "#2e6a4c";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: INK,
        }}
      >
        <svg width="126" height="126" viewBox="0 0 32 32" fill="none">
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
