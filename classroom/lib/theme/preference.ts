// 테마 선택 — 순수 함수(#398, spec #396). 쿠키 값 해석과 문서 루트에 붙일
// 표시 결정을 여기 둔다. 공개 앱의 같은 이름 파일(`frontend/lib/theme/
// preference.ts`)과 같은 모양이다 — 쿠키 도우미의 기존 복사 방식(`lib/auth/
// cookies.ts`)과 같다.
//
// **쿠키 하나로 두 앱이 공유한다.** 로그인 쿠키와 같은 부모 도메인 설정을
// 쓴다(`sessionCookieDomain`, `lib/auth/cookies.ts`) — 값이 없거나 시스템이
// 아닌 다른 문자열이면 시스템으로 본다(#397 「문서 루트에 명시적 표시가 있으면
// 그것을, 없으면 운영체제를 따른다」의 "없다" 쪽과 같은 취급).
export const THEME_COOKIE = "codemit_theme";

export type ThemePreference = "system" | "light" | "dark";

export function parseThemePreference(value: string | undefined | null): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}

/** 문서 루트(`<html>`)에 붙일 `data-theme` 값 — 시스템이면 붙이지 않는다(undefined). */
export function themeAttribute(preference: ThemePreference): "light" | "dark" | undefined {
  return preference === "system" ? undefined : preference;
}
