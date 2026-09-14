// FE-06(#31) 인수조건 — "OG 태그가 서버에서 들어가 링크 공유 시 제대로
// 미리보기된다". app/contests/[id]/opengraph-image.tsx 와 같은 Next 파일
// 컨벤션이다 — generateMetadata(../page.tsx)가 images 를 손으로 채우지 않아도
// 이 라우트가 만든 이미지를 og:image 로 자동 연결한다.
import { ImageResponse } from "next/og";

import { fetchDeveloperProfile } from "@/lib/api/developers";

export const alt = "Codemit 개발자 프로필";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function DeveloperOpengraphImage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const developerId = Number(id);
  const profile = Number.isInteger(developerId) ? await fetchDeveloperProfile(developerId) : null;

  const title = profile?.display_name ?? "Codemit";
  const subtitle = profile
    ? `아카이브된 제출작 ${profile.submissions.length}건`
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
        <div style={{ fontSize: 28, letterSpacing: 4, color: "#8B877D" }}>CODEMIT · 개발자 프로필</div>
        <div style={{ display: "flex", fontSize: 56, fontWeight: 700, marginTop: 24 }}>{title}</div>
        <div style={{ display: "flex", fontSize: 32, color: "#55524A", marginTop: 20 }}>{subtitle}</div>
      </div>
    ),
    { ...size },
  );
}
