// FE-05(#30) 인수조건 — "OG 태그(제목·설명·이미지)가 서버에서 들어간다". Next 의
// 파일 컨벤션(`opengraph-image.tsx`)을 쓰면 `generateMetadata`(../page.tsx)가 굳이
// images 를 손으로 채우지 않아도 이 라우트가 만든 이미지를 og:image 로 자동
// 연결한다 — 이미지 자체도 매 Contest 마다 서버에서 새로 그린다(정적 placeholder
// 가 아니라 제목이 실제로 들어간다).
import { ImageResponse } from "next/og";

import { fetchContest } from "@/lib/api/contests";

export const alt = "Codemit 공모전";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function ContestOpengraphImage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const contestId = Number(id);
  const contest = Number.isInteger(contestId) ? await fetchContest(contestId) : null;

  const title = contest?.title ?? "Codemit";
  const subtitle = contest
    ? `상금 ${contest.prize.toLocaleString("ko-KR")}원`
    : "발주자가 상금을 걸고 요구사항을 공개하는 공개 공모전 플랫폼";

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
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
            <path
              d="M23.07 8.93 A10 10 0 1 0 23.07 23.07"
              stroke="#8B877D"
              strokeWidth={3.6}
              strokeLinecap="round"
            />
            <circle cx="23.07" cy="23.07" r="3.9" fill="#2e6a4c" />
          </svg>
          <div style={{ fontSize: 28, letterSpacing: 4, color: "#8B877D" }}>CODEMIT</div>
        </div>
        <div style={{ display: "flex", fontSize: 56, fontWeight: 700, marginTop: 24 }}>{title}</div>
        <div style={{ display: "flex", fontSize: 32, color: "#55524A", marginTop: 20 }}>{subtitle}</div>
      </div>
    ),
    { ...size },
  );
}
