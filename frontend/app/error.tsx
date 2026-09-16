"use client";

// 화면이 깨졌을 때 사람이 보는 자리(2026-09-16). 지금까지는 이런 파일이 없어
// 프레임워크 기본 오류 화면(영어)이 그대로 나왔고, 그 오류가 어디에도 기록되지
// 않았다 — 여기서 GlitchTip 으로 보낸다.
//
// 무엇이 잘못됐는지는 적지 않는다: 오류 메시지에 내부 사정(경로·질의·키)이 섞여
// 나올 수 있어 사용자에게는 「문제가 생겼다」와 「다시 시도」만 준다. 진단은 수집된
// 오류로 한다.
import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";

import Link from "next/link";

import { PageHeader, PageShell } from "@/app/components/ui";
import { buttonClass } from "@/lib/ui/classnames";


export default function ErrorScreen({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <PageShell>
      <PageHeader
        title="문제가 생겼습니다"
        titleTestId="error-heading"
        description="잠시 후 다시 시도해주세요. 계속 같은 화면이 나오면 운영팀에 알려주세요."
      />
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={reset} data-testid="error-retry" className={buttonClass("primary")}>
          다시 시도
        </button>
        <Link href="/" data-testid="error-home-link" className={buttonClass("secondary")}>
          홈으로
        </Link>
      </div>
    </PageShell>
  );
}
