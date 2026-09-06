// 소셜 로그인 제공자 목록 — 백엔드가 실제로 구현한 셋과 정확히 같다
// (backend/accounts/social.py의 _REAL_ADAPTERS, backend/accounts/models.py의
// SocialAccount.Provider). 이 파일 하나가 그 목록의 프론트엔드 쪽 원본이다 —
// app/api/auth/social/[provider]/{login,authorize,callback}/route.ts 셋이 전부
// 이걸 참조한다. 목록이 갈라지면 백엔드는 "unsupported provider"로 401을
// 내는데, 여기서 먼저 걸러 그 왕복 없이 바로 답한다.
//
// 프레임워크·DOM·네트워크를 건드리지 않는 순수 함수라 vitest 러너로 검증할
// 수 있다(ADR-0026) — next-path.ts와 같은 자리.
export type SocialProvider = "kakao" | "github" | "google";

export const SOCIAL_PROVIDERS: readonly SocialProvider[] = ["kakao", "github", "google"];

export function isSocialProvider(value: string): value is SocialProvider {
  return (SOCIAL_PROVIDERS as readonly string[]).includes(value);
}
