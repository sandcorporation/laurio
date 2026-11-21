"use client";

// 제보 버튼 (#1242, 스펙 #1237) — 운영자가 켠 계정에만 보인다. 공개 앱과 같은 구현(`@codemit/bff-client/feedback`).
import { createBffClient } from "@codemit/bff-client";
import { FeedbackLauncher } from "@codemit/bff-client/feedback";

import { bffClient } from "@/lib/bff/client";

// 권한 조회는 세션 되살리기 없는 클라이언트로 — 로그인 전 방문자가 재시도를 만들지 않는다.
const permissionClient = createBffClient({ onUnauthorized: () => {} });

export function FeedbackButton() {
  return <FeedbackLauncher client={bffClient} permissionClient={permissionClient} app="classroom" myReportsHref="/feedback" />;
}
