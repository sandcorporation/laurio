// 기본 OG 이미지(#394, #391 Implementation Decisions) — 공모전 상세·개발자
// 프로필처럼 자기 `opengraph-image.tsx`가 없는 화면(홈·공모전 목록 등)이
// 공유될 때 이 이미지가 쓰인다. 로고(심볼+워드마크)와 이 서비스가 공모전만
// 말한다는 한 줄 설명을 담는다 — `app/layout.tsx`의 기본 설명과 같은 문장이다.
import { ImageResponse } from "next/og";

export const alt = "Codemit";
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
          <div style={{ display: "flex", fontSize: 44, fontWeight: 700 }}>Codemit</div>
        </div>
        <div style={{ display: "flex", fontSize: 32, color: "#55524A", marginTop: 28 }}>
          발주자가 상금을 걸고 요구사항을 공개하면, 개발자들이 만들어 제출하는 공개 공모전 플랫폼
        </div>
      </div>
    ),
    { ...size },
  );
}
