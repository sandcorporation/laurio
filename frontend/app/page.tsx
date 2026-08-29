// 뼈대 단계의 자리표시 페이지다. 실제 공개 표면(공모전 목록)은 티켓 FE-04(#29)가
// 이 자리를 대신한다. 여기서는 티켓 FE-02(#27)의 토큰이 실제로 배선돼 있다는
// 것만 증명한다 — 화면을 만들지 않는다. 아래 스트립은 frontend/e2e/tokens.spec.ts
// 가 계산된 스타일을 읽는 대상이다. 리터럴 hex 는 어디에도 없다 — 전부
// app/tokens.css 의 @theme 가 만든 유틸리티(`bg-*` `text-*` `border-*`)다.
//
// 서버 컴포넌트다. 이 페이지에 "use client" 가 붙으면 안 된다(ADR-0015).
export default function Home() {
  return (
    <main className="flex min-h-screen flex-col gap-8 p-10">
      <h1 className="text-3xl font-semibold">Laurio</h1>
      <p>공개 공모전 플랫폼. 프론트엔드 뼈대가 서 있습니다.</p>

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
