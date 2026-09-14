// 홈 화면 추가 아이콘 — `app/icon.tsx`와 같은 그림을 더 큰 캔버스(180×180,
// Apple 관례)에 여백을 두어 그린다. 색·도형 정의는 그쪽 주석 참고.
import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

const ATTENTION = "#c4442b";
const PAPER = "#f5f3ec";

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
          background: ATTENTION,
        }}
      >
        <svg width="126" height="126" viewBox="0 0 32 32" fill="none">
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
