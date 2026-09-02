import { notFound } from "next/navigation";

import { isDeployedEnvironment } from "@/lib/auth/cookies";

// 토큰 배선 증명 페이지(FE-02 #27이 세운 단언, #93이 현관에서 옮겼다).
//
// `/` 는 FE-02 시절 이 스트립을 담은 자리표시 페이지였다 — 이제 `/` 는 실제
// 공모전을 보여주는 공개 표면이라(#93, spec #92) 이 진단용 마크업이 거기 있으면
// 안 된다. `data-token-proof` 네 개는 그대로 옮겨왔을 뿐 값도 의미도 바뀌지
// 않았다 — frontend/e2e/tokens.spec.ts 가 여전히 이 스트립의 계산된 스타일을
// 읽는다(이제 이 경로에서). 리터럴 hex 는 여기도 없다 — 전부 app/tokens.css 의
// `@theme` 가 만든 유틸리티(`bg-*` `text-*` `border-*`)다.
//
// 이 페이지는 헤더 어디에서도 링크되지 않는다 — 첫 방문자가 걸어서 닿을 이유가
// 없는 진단 화면이라 "현관이 아닌 곳"이라는 조건을 그렇게 지킨다. 색인 대상도
// 아니므로 서버/클라이언트 컴포넌트 여부는 의미가 없지만, 굳이 클라이언트로
// 바꿀 이유도 없어 서버 컴포넌트로 남긴다.
//
// **배포 환경에서는 404 다**(#93 코드리뷰). 미들웨어(middleware.ts) 매처는
// `/console/:path*` 뿐이라 이 경로는 그 가드 밖이고, robots 도 이 경로를 막지
// 않는다 — 게이트 없이 두면 staging/production 호스트에 주인 없는 진단 화면이
// 그대로 200 으로 뜬다. 시크릿이 새는 것은 아니지만("아무 의미도 없는 값 넷"),
// 운영 호스트에 목적을 알 수 없는 페이지가 살아 있는 것 자체가 사고다.
// `lib/auth/cookies.ts` 의 `isDeployedEnvironment()` 를 그대로 재사용한다 —
// "배포 환경인가"의 판정이 여기서 다시 발명되면 두 곳이 어긋날 수 있다.
// `tokens.spec.ts` 는 dev 스택에서만 도므로 이 게이트에 비용이 없다.
export default function DevTokensPage() {
  if (isDeployedEnvironment()) {
    notFound();
  }

  return (
    <main className="flex min-h-screen flex-col gap-8 p-10">
      <h1 className="text-3xl font-semibold">토큰 배선 증명</h1>
      <p>
        이 화면은 사용자용이 아니다 — app/tokens.css 의 값이 실제로 렌더링에 배선돼
        있는지만 증명한다.
      </p>

      <div className="flex flex-wrap items-center gap-4 rounded-md border border-rule bg-surface p-4">
        <span
          data-token-proof="attention"
          className="rounded-sm border border-attention px-3 py-1 text-sm text-attention"
        >
          상금미달
        </span>
        <span
          data-token-proof="verified"
          className="rounded-sm border border-verified px-3 py-1 text-sm text-verified"
        >
          충족
        </span>
        {/* 금액·기한·식별자는 모노스페이스로 렌더된다(FE-02 승인 기준). */}
        <span data-token-proof="amount" className="font-mono text-base">
          4,000,000
        </span>
        <span data-token-proof="deadline" className="font-mono text-sm text-ink">
          D-6
        </span>
      </div>
    </main>
  );
}
