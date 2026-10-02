"use client";

// 헤더의 테마 버튼(#422, #398). 공개 앱·강의실의 같은 이름 컴포넌트와 같은
// 모양이다(`frontend/app/components/theme-toggle.tsx`). 시스템·라이트·다크 중
// 하나를 고른다. 서버(RootLayout)가 쿠키를 읽어 준 초기값으로 시작해 첫
// 렌더부터 현재 선택을 안다 — 쿠키가 httpOnly라 클라이언트가 document.cookie로
// 다시 읽을 수 없다.
//
// 누르면 두 가지를 한다: (1) 문서 루트의 data-theme 속성을 그 자리에서 바꿔
// 새로고침 없이 반영하고, (2) `/api/theme`를 불러 쿠키에 저장한다 — 실패해도
// 화면은 이미 바뀌어 있으므로 다시 시도하지 않는다.
//
// 로그인 여부와 무관하게 항상 보인다 — 세션을 확인하지 않는다.
import { useState } from "react";

import { parseThemePreference, themeAttribute, type ThemePreference } from "@/lib/theme/preference";

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
  // 문서 루트의 표시가 지금 선택이다 — 좁은 화면의 메뉴 덮개는 열 때마다 이 버튼을
  // 새로 그리므로(#523), 서버가 준 첫 값만 믿으면 덮개 안에서 바꾼 뒤 다시 열었을 때
  // 옛 값을 보인다. 서버 렌더에서는 문서가 없으니 첫 값을 쓴다 — 첫 화면에서는
  // 그 둘이 같다(RootLayout 이 같은 값으로 표시를 붙인다).
  const [preference, setPreference] = useState<ThemePreference>(() =>
    typeof document === "undefined"
      ? initialPreference
      : parseThemePreference(document.documentElement.getAttribute("data-theme")),
  );
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
        className="border border-rule bg-transparent px-2.5 py-1 text-[11.5px] font-normal text-ink/62 hover:border-ink hover:text-ink"
      >
        테마: {currentLabel}
      </button>

      {open && (
        <>
          <button
            type="button"
            aria-label="메뉴 닫기"
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-10 w-auto cursor-default border-0 bg-transparent"
          />
          <div
            data-testid="theme-toggle-panel"
            role="menu"
            aria-label="테마 선택"
            className="absolute left-0 z-20 mt-1.5 flex w-32 flex-col border border-rule bg-surface text-[13px]"
          >
            {OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="menuitemradio"
                aria-checked={option.value === preference}
                data-testid={`theme-toggle-option-${option.value}`}
                onClick={() => choose(option.value)}
                className="w-auto border-0 bg-transparent px-3 py-2 text-left font-normal text-ink hover:bg-paper"
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
