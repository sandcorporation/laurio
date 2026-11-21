"use client";

// 제보 버튼 (#1241, 스펙 #1237) — 운영자가 켠 계정에만 보인다. 구현은 `@codemit/bff-client/feedback`.
import { FeedbackLauncher } from "@codemit/bff-client/feedback";

import { bffClient } from "@/lib/bff/client";
import { sessionOnlyClient } from "@/lib/bff/session-client";

export function FeedbackButton() {
  return (
    <FeedbackLauncher
      client={bffClient}
      permissionClient={sessionOnlyClient}
      app="contest"
      myReportsHref="/console/feedback"
    />
  );
}
