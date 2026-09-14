"use client";

// 헤더의 테마 버튼 — 공개 앱(frontend/app/components/theme-toggle.tsx)과 같은
// 모양이다(#398, spec #396). 시스템·라이트·다크 중 하나를 고른다.
//
// 서버(RootLayout)가 쿠키를 읽어 준 초기값으로 시작해 첫 렌더부터 현재 선택을
// 안다 — 쿠키가 httpOnly라 클라이언트가 document.cookie로 다시 읽을 수 없다
// (로그인 쿠키와 같은 이유, lib/auth/cookies.ts).
//
// 누르면 두 가지를 한다: (1) 문서 루트의 data-theme 속성을 그 자리에서 바꿔
// 새로고침 없이 반영하고(#397의 light-dark()/color-scheme 규칙이 그 속성을
// 본다), (2) `/api/theme`를 불러 쿠키에 저장한다 — 그 쿠키는 공개 앱과
// 부모 도메인을 공유하므로(ADR-0038과 같은 원칙) 여기서 고른 값이 공개 앱에도
// 그대로 적용된다.
//
// 로그인 여부와 무관하게 항상 보인다(spec #396 user story 9) — `AccountMenu`
// 처럼 세션을 확인하지 않는다.
import { useState } from "react";

import { themeAttribute, type ThemePreference } from "@/lib/theme/preference";

const OPTIONS: Array<{ value: ThemePreference; label: string }> = [
  { value: "system", label: "시스템" },
  { value: "light", label: "라이트" },
  { value: "dark", label: "다크" },
];

function applyThemeAttribute(preference: ThemePreference): void {
  const attribute = themeAttribute(preference);
  if (attribute) {
    document.documentElement.setAttribute("data-theme", attribute);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
}

export function ThemeToggle({ initialPreference }: { initialPreference: ThemePreference }) {
  const [preference, setPreference] = useState(initialPreference);
  const [open, setOpen] = useState(false);

  async function choose(next: ThemePreference) {
    setPreference(next);
    setOpen(false);
    applyThemeAttribute(next);
    await fetch("/api/theme", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ preference: next }),
    }).catch(() => undefined);
  }

  const currentLabel = OPTIONS.find((option) => option.value === preference)?.label ?? "시스템";

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        data-testid="theme-toggle-trigger"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={`테마: ${currentLabel}, 누르면 테마를 고른다`}
        className="border border-rule px-3 py-1.5 text-[13px] text-ink hover:border-ink"
      >
        테마: {currentLabel}
      </button>

      {open && (
        <>
          <button
            type="button"
            aria-label="메뉴 닫기"
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-10 cursor-default"
          />
          <div
            data-testid="theme-toggle-panel"
            role="menu"
            aria-label="테마 선택"
            className="absolute right-0 z-20 mt-1.5 flex w-32 flex-col border border-rule bg-surface text-[13px]"
          >
            {OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="menuitemradio"
                aria-checked={option.value === preference}
                data-testid={`theme-toggle-option-${option.value}`}
                onClick={() => choose(option.value)}
                className="px-3 py-2 text-left text-ink hover:bg-paper"
              >
                {option.value === preference ? "✓ " : ""}
                {option.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
