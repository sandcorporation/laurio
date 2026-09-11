// 계정 메뉴에 보일 이름을 정하는 자리 (#306 후속).
//
// **react 를 보지 않는다** — 순수 함수 시임(ADR-0026)에서 단위 테스트로 고정하려면
// 그래야 하고, 러너의 pure-module-guard 가 그것을 강제한다. 그래서 훅(`use-me.ts`)
// 안에 두지 않고 이 파일로 뺐다.

/** 계정 메뉴에 보일 이름.
 *
 * 이메일이 있으면 그것을, 없으면 중립적인 말을 쓴다 — 카카오는 이메일을 주지
 * 않을 수 있고, 그때 `username` 은 `kakao:<제공자id>` 다. 그 문자열은 계정을
 * 유일하게 가리키려고 만든 것이지 사람이 읽으라고 만든 것이 아니다.
 * staging 을 브라우저로 걸어 보다 헤더에 그 값이 그대로 떠 있는 것을 봤다. */
export function accountLabel(me: { username: string; email: string }): string {
  const email = me.email.trim();
  if (email) return email;
  return "내 계정";
}
