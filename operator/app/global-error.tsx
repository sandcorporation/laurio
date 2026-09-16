"use client";

// 레이아웃 자체가 깨졌을 때의 마지막 그물(2026-09-16). `error.tsx` 는 레이아웃 안에서
// 그려지므로 레이아웃이 터지면 잡지 못한다 — 이 파일은 자기 `<html>`·`<body>` 를
// 들고 나오고, 그래서 앱의 서체·토큰 없이 브라우저 기본 모양으로 보인다. 그 대신
// 어떤 상황에서도 뜬다.
import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";

export default function GlobalError({ error }: { error: Error & { digest?: string } }) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="ko">
      <body style={{ fontFamily: "system-ui, sans-serif", padding: "3rem 1.5rem", lineHeight: 1.6 }}>
        <h1 style={{ fontSize: "1.25rem", margin: 0 }}>문제가 생겼습니다</h1>
        <p>화면을 새로 고쳐 보세요. 계속 같은 화면이 나오면 운영팀에 알려주세요.</p>
        <p>
          <a href="/">홈으로</a>
        </p>
      </body>
    </html>
  );
}
