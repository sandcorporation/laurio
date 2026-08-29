// 프록시 경로 세그먼트 안전성 검사 (ADR-0016, FE-08 #33 — 코드리뷰 지적 수정).
//
// **버그였던 것**: `app/api/backend/[...path]/route.ts`가 Next의 catch-all
// 파라미터 `path: string[]`를 `path.join("/")`로 이어붙여 `backendPath`를
// 만들고, `isAllowedBackendPath(backendPath)`로 "검사"한 뒤, 바로 그 문자열을
// `forward.ts`가 `fetch(url)`에 그대로 붙여 "실행"했다. 그런데 Next는 라우트
// 파라미터를 이미 URL 디코드해서 넘긴다 — 그래서 세그먼트 하나 안에 인코딩된
// 슬래시(`%2f`)를 숨기면 이런 일이 벌어진다:
//
//   요청 경로:  /api/backend/contests/..%2finternal%2ftick
//   Next params: ["contests", "../internal/tick"]      ← %2f 가 / 로 디코드됨
//   backendPath(수정 전): "/api/contests/../internal/tick"
//     → isAllowedBackendPath는 "/api/contests"로 시작한다는 이유로 통과시킨다
//     → 그런데 fetch()에 넘기는 순간 URL 파서가 ".."를 정규화해 실제 요청은
//       "/api/internal/tick"으로 나간다 — **검사한 문자열과 실제로 실행한
//       문자열이 다르다.**
//
// 직접 재현해 확인했다: 이 경로로 스케줄러 틱·채점·환불·배분 내부
// 엔드포인트에 프록시의 404가 아니라 백엔드(InternalAuth)의 401이 그대로
// 돌아왔다 — 요청이 실제로 /api/internal/*까지 도달했다는 뜻이다. 허용목록
// (첫 번째 방어선)이 뚫렸고, 백엔드의 INTERNAL_API_TOKEN 검사(두 번째
// 방어선)만 버텨준 것이다.
//
// **고친 방법**: 두 겹으로 막는다.
//   1) 세그먼트 단위 방어 — catch-all의 정상적인 세그먼트는 애초에 "/"나
//      "\"를 포함할 수 없다(그 자체가 경로 구분자다). "."·".."이어서도 안
//      된다(경로 순회). 하나라도 걸리면 그 요청 전체를 기본 거부한다.
//   2) 구조적 보장 — 세그먼트마다 `encodeURIComponent`로 다시 인코딩해
//      백엔드로 보낼 경로 문자열을 조립한 뒤, 그 문자열을 URL 정규화에 통과시켜
//      원본과 달라지면(=조립 결과에 아직도 정규화될 여지가 있다는 뜻이면)
//      거부한다. 1)이 이미 모든 경우를 막지만, 이후 누군가 1)의 조건을 실수로
//      완화해도 2)가 마지막 방어선으로 남는다 — "검사 대상 == 실행 대상"이
//      코드 구조로 보장되게 한다.

function isSafeSegment(segment: string): boolean {
  if (segment === "" || segment === "." || segment === "..") return false;
  if (segment.includes("/") || segment.includes("\\")) return false;
  return true;
}

/**
 * catch-all 세그먼트 배열을 백엔드로 보낼 안전한 경로 문자열로 조립한다.
 * 세그먼트 중 하나라도 경로 구분자·경로 순회로 의심되면 `null`을 반환한다 —
 * 호출부는 이를 "허용목록에 없는 경로"와 같은 404로 처리하면 된다(기본 거부
 * 원칙은 두 실패 모두에 동일하게 적용된다).
 */
export function sanitizeBackendPath(segments: string[]): string | null {
  if (segments.length === 0) return null;
  if (!segments.every(isSafeSegment)) return null;

  const candidate = `/api/${segments.map(encodeURIComponent).join("/")}`;

  // 최후의 구조적 확인 — 조립 결과를 URL 정규화에 통과시켜 원본과 비교한다.
  // encodeURIComponent를 거친 세그먼트는 "/"·".."이 전부 퍼센트 인코딩돼
  // 있으므로 정상적으로는 항상 같아야 한다 — 달라지면 무조건 거부한다.
  const normalized = new URL(candidate, "http://internal.invalid").pathname;
  if (normalized !== candidate) return null;

  return candidate;
}
