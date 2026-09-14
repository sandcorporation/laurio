// 랜딩 OG 이미지(#395, #391 Implementation Decisions) — 로고(심볼+워드마크)와
// 한 줄 소개를 담는다. 강의실에서 공유될 화면은 사실상 랜딩("/") 하나뿐이라
// 루트에 둔다(공개 앱의 `app/opengraph-image.tsx`와 같은 컨벤션).
import { ImageResponse } from "next/og";

export const alt = "Codemit 클래스";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const INK = "#17160f";
const VERIFIED = "#2e6a4c";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "80px",
          backgroundColor: "#F5F3EC",
          color: "#17160F",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <svg width="64" height="64" viewBox="0 0 32 32" fill="none">
            <path
              d="M23.07 8.93 A10 10 0 1 0 23.07 23.07"
              stroke={INK}
              strokeWidth={3.6}
              strokeLinecap="round"
            />
            <circle cx="23.07" cy="23.07" r="3.9" fill={VERIFIED} />
          </svg>
          <div style={{ display: "flex", fontSize: 44, fontWeight: 700 }}>Codemit 클래스</div>
        </div>
        <div style={{ display: "flex", fontSize: 32, color: "#55524A", marginTop: 28 }}>
          문제를 내면 AI가 코드를 항목별로 채점하는 클래스 도구
        </div>
      </div>
    ),
    { ...size },
  );
}
