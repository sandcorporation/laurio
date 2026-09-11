// "next" 목적지 검증(#95, spec #92) — 서버(라우트 핸들러)와 클라이언트(로그인
// 화면이 실물 카카오 버튼의 href를 조립할 때) 양쪽에서 쓴다. Node 전용 API를
// 쓰지 않는다 — lib/auth/oauth-state.ts가 이 파일과 별개인 이유가 그것이다:
// 그쪽은 node:crypto(randomBytes)를 쓰는 서버 전용 코드라, 클라이언트 컴포넌트인
// app/login/login-form.tsx가 그 모듈을 그대로 import하면 webpack이 브라우저
// 번들에 node:crypto를 끌고 가려다 빌드가 깨진다(직접 재현해 확인했다) — 순수
// 검증 로직만 이 파일로 분리해 그 경로를 피한다.
//
// **문자 블랙리스트가 아니라 실제 파싱 결과로 판정한다**(코드리뷰 지적 —
// 리뷰어가 실물로 재현했다). 예전 구현은 "//"로 시작하는지, "://"를 포함하는지만
// 봤는데, `next=%2F%5Cevil.example.test`(디코드하면 "/\evil.example.test")가
// 그 검사를 통과해 콜백의 `new URL(next, origin)`이 이걸 "//evil.example.test"로
// 정규화해 오픈 리다이렉트가 됐다 — WHATWG URL 파서는 http/https 같은 특수
// 스킴에서 "\"를 "/"와 동일하게 취급하고(선두의 두 슬래시-유사 문자를 만나면
// authority 파싱 상태로 들어간다), TAB·개행·캐리지리턴은 파싱 첫 단계에서
// 조용히 제거한다. 둘 다 문자열 검사로는 끝없이 새 우회를 낳는다 — 그래서
// packages/bff-shared/src/path-safety.ts의 sanitizeBackendPath와 같은 기법을
// 쓴다: 의미 없는 placeholder 오리진을 기준으로 실제로 `new URL()`에 태워
// 보고, 그 결과가 여전히 그 placeholder를 가리키는지(=다른 호스트로 새지
// 않았는지)를 구조적으로 확인한다. 이러면 backslash·제어문자를 포함해 아직
// 발견되지 않은 정규화 트릭까지 같은 검사 하나로 막는다.
const SAFE_NEXT_PATH_BASE = "http://laurio-internal.invalid";

export function isSafeNextPath(next: string | null | undefined): next is string {
  if (!next) return false;
  if (!next.startsWith("/")) return false;

  let resolved: URL;
  try {
    resolved = new URL(next, SAFE_NEXT_PATH_BASE);
  } catch {
    return false;
  }

  // 파싱 결과가 placeholder 오리진을 벗어났다면(backslash가 "/"로 정규화돼
  // "//evil.example.com"이 되는 경우 등) next는 실제로 다른 호스트를 가리킨다.
  return resolved.protocol === "http:" && resolved.host === "laurio-internal.invalid";
}

export function resolveNextPath(next: string | null | undefined, fallback = "/console"): string {
  return isSafeNextPath(next) ? next : fallback;
}

// `next_origin`을 요청했는데(강의실 같은 형제 오리진에서 왔다는 뜻이다) 허용목록과
// 대조하는 resolveSiblingOrigin(lib/auth/sibling-origins.ts)이 실패하면, 그 요청에
// 딸려 온 `next`는 이 오리진 안에서는 의미가 없다(#334 코드리뷰 지적) — 형제 앱의
// 경로(`/join/abc123` 등)일 수 있고, 그걸 이 오리진 안에서 그대로 리다이렉트하면
// 여기 없는 경로라 404가 난다. 예전에는 강의실이 `next`를 항상 "/"로 고정해 보냈기
// 때문에 이 경로가 없었다 — 강의실이 실제 목적지를 실어 보내기 시작하면서(#334)
// 처음으로 생긴 위험이다.
//
// `next_origin`이 애초에 없었으면(형제 오리진에서 온 요청이 아닌 평범한 공개 앱
// 로그인) `next`는 손대지 않는다 — 지금까지와 한 글자도 다르지 않다.
export function withoutForeignNext(
  next: string,
  requestedNextOrigin: string | null | undefined,
  returnOrigin: string | null,
  fallback = "/console",
): string {
  return requestedNextOrigin && !returnOrigin ? fallback : next;
}
