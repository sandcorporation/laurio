// 헤더 검색창(#449, 부모 #444 스펙) — `GET /contests?q=…` 로 가는 평범한 폼이라
// JS 없이도 동작한다. 서버 컴포넌트로 둔다(`site-header.tsx`가 이미 그렇다) —
// 색인 대상 공개 페이지에 실리는 헤더의 일부라 ADR-0015 의 경계를 지킨다.
//
// **넓은 화면은 항상 펼쳐져 있고, 좁은 화면은 아이콘 뒤에 접혀 있다.** 자바스크립트
// 없이도 접고 펼 수 있어야 하므로 `<details>`/`<summary>`(브라우저 내장 토글)를
// 쓴다 — `useState` 로 만든 접이식은 JS 가 없으면 항상 닫힌 채로 보인다. `hidden
// md:flex`/`md:hidden` 로 두 형태 중 화면 폭에 맞는 하나만 보인다.
import { buttonClass } from "@/lib/ui/classnames";

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      className={className}
      aria-hidden="true"
    >
      <circle cx="8.5" cy="8.5" r="5.5" />
      <path d="M16.5 16.5 13 13" />
    </svg>
  );
}

// 데스크톱·모바일 두 폼이 같은 페이지에 동시에(하나는 `hidden`으로) 존재하므로
// `id`가 겹치면 안 된다 — `<label htmlFor>` 연결이 둘 다 첫 번째 `id`만 가리키게
// 된다. 인스턴스마다 고유한 `id`를 받는다.
function SearchInput({ inputId }: { inputId: string }) {
  return (
    <>
      <label htmlFor={inputId} className="sr-only">
        공모전 검색
      </label>
      <input
        id={inputId}
        data-testid="header-search-input"
        type="search"
        name="q"
        placeholder="공모전 검색"
        className="w-full min-w-0 border border-rule bg-surface px-3 py-1.5 text-[13px] text-ink placeholder:text-ink/40 focus:border-ink focus:outline-none"
      />
    </>
  );
}

export function HeaderSearch() {
  return (
    <>
      {/* 넓은 화면 — 항상 보인다. */}
      <form
        action="/contests"
        method="get"
        role="search"
        data-testid="header-search-form"
        className="hidden w-[220px] items-center md:flex"
      >
        <SearchInput inputId="header-search-q-desktop" />
      </form>

      {/* 좁은 화면 — 아이콘을 누르면 펼쳐진다. `<details>` 는 자바스크립트 없이도
          토글된다(브라우저 내장 동작). */}
      <details className="relative md:hidden">
        <summary
          data-testid="header-search-toggle"
          aria-label="공모전 검색"
          className={`${buttonClass("secondary", "sm")} cursor-pointer list-none [&::-webkit-details-marker]:hidden`}
        >
          <SearchIcon className="h-4 w-4" />
        </summary>
        <form
          action="/contests"
          method="get"
          role="search"
          data-testid="header-search-form-mobile"
          className="absolute right-0 top-full z-10 mt-2 flex w-[240px] border border-rule bg-surface p-2"
        >
          <SearchInput inputId="header-search-q-mobile" />
        </form>
      </details>
    </>
  );
}
