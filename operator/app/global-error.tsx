"use client";

// 레이아웃 자체가 깨졌을 때의 마지막 그물(2026-09-16, #427 — 색만 토큰과
// 맞춘다). `error.tsx` 는 레이아웃 안에서 그려지므로 레이아웃이 터지면 잡지
// 못한다 — 이 파일은 자기 `<html>`·`<body>` 를 들고 나온다. `app/layout.tsx`
// 가 렌더되지 않으므로 그 파일이 불러오는 `globals.css`(Tailwind·`@theme`
// 토큰)도 같이 빠진다 — 그래서 여기만 유틸리티 클래스 대신 인라인 `style` 로
// 색을 직접 적는다. 값은 `app/tokens.css` 라이트 테마 그대로다 — 레이아웃이
// 죽은 자리라 다크 전환은 못 하지만, 적어도 같은 브랜드 색으로는 보인다.
//
// **`brand-guard.test.ts`가 이 문자열도 읽는다** — 그 검사는 클래스 속성이
// 아니라 소스의 문자열 리터럴 전부를 훑는다(주석 참고). 다만 유틸리티 모양의
// 낱말만 걸리므로 `#17160f`처럼 hex 로 적은 색은 안 걸린다 — hex 값을 그대로
// 쓴다.
import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";

const INK = "#17160f";
const PAPER = "#f5f3ec";
const SURFACE = "#fffefa";
const RULE = "#ddd9ce";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="ko">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: PAPER,
          color: INK,
          fontFamily: "Pretendard, 'Malgun Gothic', 'Apple SD Gothic Neo', system-ui, sans-serif",
        }}
      >
        <div
          style={{
            maxWidth: "20rem",
            border: `1px solid ${RULE}`,
            background: SURFACE,
            padding: "2rem",
          }}
        >
          <h1 style={{ fontSize: "1.1875rem", fontWeight: 600, margin: 0 }}>문제가 생겼습니다</h1>
          <p style={{ marginTop: "0.4rem", fontSize: "0.78125rem", color: "rgba(23,22,15,0.62)" }}>
            화면을 새로 고쳐 보세요. 계속 같은 화면이 나오면 운영팀에 알려주세요.
          </p>
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
            <button
              type="button"
              onClick={reset}
              data-testid="global-error-retry"
              style={{
                border: `1px solid ${INK}`,
                background: INK,
                color: PAPER,
                padding: "0.375rem 0.75rem",
                fontSize: "0.78125rem",
                cursor: "pointer",
              }}
            >
              다시 시도
            </button>
            <a
              href="/"
              data-testid="global-error-home-link"
              style={{
                border: `1px solid ${RULE}`,
                background: SURFACE,
                color: INK,
                padding: "0.375rem 0.75rem",
                fontSize: "0.78125rem",
                textDecoration: "none",
              }}
            >
              홈으로
            </a>
          </div>
        </div>
      </body>
    </html>
  );
}
