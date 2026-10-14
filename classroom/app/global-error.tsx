"use client";

// 레이아웃 자체가 깨졌을 때의 마지막 그물(2026-09-16). `error.tsx` 는 레이아웃 안에서
// 그려지므로 레이아웃이 터지면 잡지 못한다 — 이 파일은 자기 `<html>`·`<body>` 를
// 들고 나오고, 그래서 앱의 서체·토큰 없이 브라우저 기본 모양으로 보인다. 그 대신
// 어떤 상황에서도 뜬다.
//
// **공개 설정 스크립트(`window.__CODEMIT_PUBLIC__`, #711)는 여기 싣지 못한다**(#727). 이 파일은 Next 가
// 클라이언트 컴포넌트로만 받아 서버 env 를 읽을 자리가 없고, 루트 레이아웃이 죽었으니 레이아웃의
// `<head>` 스크립트도 없다. 그래서 **첫 요청에서** 레이아웃이 죽으면 브라우저 Sentry 는 DSN 이 없어
// 켜지지 않고 아래 `captureException` 은 아무 데도 가지 않는다. 그 오류는 서버에서 났으므로 서버
// `onRequestError`(`instrumentation.ts`)가 GlitchTip 에 올린다 — 잃는 것은 같은 오류의 브라우저 쪽
// 사본뿐이다. 이미 떠 있던 화면에서 레이아웃이 터진 경우에는 설정이 남아 있어 그대로 올라간다.
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
