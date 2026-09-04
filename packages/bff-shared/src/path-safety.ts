// 프록시 경로 세그먼트 안전성 검사 (ADR-0016/0021, FE-08 #33 — 코드리뷰 지적 수정,
// 운영자 앱 04 #62로 공유 패키지에 옮김).
//
// **버그였던 것** (공개 앱에서 실제로 재현됐다): catch-all 라우트 핸들러가 Next의
// 파라미터 `path: string[]`를 `path.join("/")`로 이어붙여 `backendPath`를 만들고,
// 허용목록 검사로 "검사"한 뒤, 바로 그 문자열을 `fetch(url)`에 그대로 붙여
// "실행"했다. 그런데 Next는 라우트 파라미터를 이미 URL 디코드해서 넘긴다 — 그래서
// 세그먼트 하나 안에 인코딩된 슬래시(`%2f`)를 숨기면 이런 일이 벌어진다:
//
//   요청 경로:  /api/backend/contests/..%2finternal%2ftick
//   Next params: ["contests", "../internal/tick"]      ← %2f 가 / 로 디코드됨
//   backendPath(수정 전): "/api/contests/../internal/tick"
//     → 허용목록 검사는 "/api/contests"로 시작한다는 이유로 통과시킨다
//     → 그런데 fetch()에 넘기는 순간 URL 파서가 ".."를 정규화해 실제 요청은
//       "/api/internal/tick"으로 나간다 — **검사한 문자열과 실제로 실행한
//       문자열이 다르다.**
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
//
// 이 파일에 경로 문자열은 없다 — 어떤 접두어를 허용할지는 앱마다 자기 목록을
// 갖는다(ADR-0021). 여기 있는 것은 "세그먼트가 안전한가"라는, 목록 내용과
// 무관한 검사뿐이다.

function isSafeSegment(segment: string): boolean {
  if (segment === "" || segment === "." || segment === "..") return false;
  if (segment.includes("/") || segment.includes("\\")) return false;
  return true;
}

/**
 * 2차 방어선만 단독으로 노출한다(#161) — 세그먼트를 인코딩해 조립한 뒤 URL
 * 정규화에 통과시켜 원본과 비교한다. `sanitizeBackendPath`는 이 함수 앞에 항상
 * `isSafeSegment` 게이트(1차 방어선)를 두므로, **정상 경로에서는 이 함수 혼자
 * 거부를 낼 일이 없다** — 그래서 e2e로는 1차를 실수로 완화하지 않는 한 이 함수가
 * 실제로 무언가를 거부하는 순간에 구조상 도달할 수 없다(도달하려면 1차가 이미
 * 뚫려 있어야 하는데, 뚫려 있다는 것 자체가 사고다).
 *
 * 그래서 이 함수를 따로 내보낸다 — 테스트가 `isSafeSegment`를 우회해(1차가 없다고
 * 가정하고) 이 함수를 직접 불러 "1차가 실수로 완화돼도 2차가 여전히 거부하는가"를
 * 직접 확인할 수 있게 한다. `sanitizeBackendPath.test.ts`의 "2차 방어선" 절이 그
 * 시나리오다.
 */
export function assembleAndVerifyBackendPath(segments: string[]): string | null {
  const candidate = `/api/${segments.map(encodeURIComponent).join("/")}`;

  // 최후의 구조적 확인 — 조립 결과를 URL 정규화에 통과시켜 원본과 비교한다.
  // encodeURIComponent를 거친 세그먼트는 "/"·".."이 전부 퍼센트 인코딩돼
  // 있으므로 정상적으로는 항상 같아야 한다 — 달라지면 무조건 거부한다.
  const normalized = new URL(candidate, "http://internal.invalid").pathname;
  if (normalized !== candidate) return null;

  return candidate;
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

  return assembleAndVerifyBackendPath(segments);
}
