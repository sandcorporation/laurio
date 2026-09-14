// 로고 심볼 — 「커밋 노드 C」(#391, 확정 후보 A, 2026-09-14). 열린 C 호의
// 오른쪽 아래 끝에 통과 초록 노드가 붙는다. 32×32 격자, 도형 정의는 #391
// Implementation Decisions 그대로다(획 3.6, 노드 반경 3.9).
//
// 획은 잉크(다크 테마에서는 종이색)를 `currentColor`로 받고, 노드는 테마와
// 무관하게 항상 통과 초록이다(#391 Implementation Decisions 「헤더」).
//
// **원본은 이 파일이다.** `classroom/app/components/logo-mark.tsx`는 토큰
// 파일과 같은 방식으로 둔 복사본이고(#298), 두 파일이 한 글자라도 갈리면
// `classroom/lib/design/logo-mark.test.ts`가 빨개진다.
export function LogoMark({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} fill="none" aria-hidden="true">
      <path
        d="M23.07 8.93 A10 10 0 1 0 23.07 23.07"
        stroke="currentColor"
        strokeWidth={3.6}
        strokeLinecap="round"
        className="text-ink dark:text-paper"
      />
      <circle cx={23.07} cy={23.07} r={3.9} className="fill-verified" />
    </svg>
  );
}
