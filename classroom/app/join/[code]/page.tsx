// 가입 링크 (#280) 의 서버 껍데기(#788). 화면은 `join-view.tsx`(클라이언트)가 그대로 그리고,
// 이 파일은 메신저·SNS 크롤러가 읽는 공유 카드 `<head>` 만 서버에서 만든다. 카드 규칙(무엇을
// 싣고 무엇을 안 싣는지)은 `lib/join/share-metadata.ts`. `robots` 는 레이아웃 기본
// (`index: false, follow: false`)을 그대로 쓴다 — 가입 코드는 반쯤 비공개 주소다.
import type { Metadata } from "next";

import { backendBaseUrl } from "@/lib/auth/backend";
import { fetchJoinPreviewForCard, joinShareMetadata } from "@/lib/join/share-metadata";

import { JoinView } from "./join-view";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ code: string }>;
}): Promise<Metadata> {
  const { code } = await params;
  return joinShareMetadata(await fetchJoinPreviewForCard(backendBaseUrl(), code));
}

export default function JoinPage() {
  return <JoinView />;
}
