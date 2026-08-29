// 생성된 타입을 실제로 쓰는 예시 호출(FE-03, #28 인수조건).
//
// `GET /api/contests/categories` 는 공개 표면이다(auth=None, ADR-0015) — 로그인
// 없이 카테고리 목록을 내려준다. `Category` 는 `id`(number)·`name`(string) 두
// 필드뿐이라 백엔드 스키마 변화를 눈으로 확인하기 좋은 최소 예시다.
//
// 반환 타입은 100% `schema.gen.ts` 에서 온다 — 여기서 직접 선언하지 않는다.
// 백엔드가 필드를 지우거나 이름을 바꾸면 `res.data![0].그필드` 를 쓰는 곳마다
// `tsc --noEmit` 이 즉시 실패한다(런타임이 아니라 빌드타임).
import { backendClient } from "./client";
import type { components } from "./schema.gen";

export type Category = components["schemas"]["CategoryOut"];
export type DeliverableType = components["schemas"]["DeliverableTypeOut"];
export type Contest = components["schemas"]["ContestOut"];

// 목록은 페이지네이션된다(백엔드 ninja PageNumberPagination, 기본 20개/페이지).
// FE-04(#29)의 필터·정렬은 백엔드에 쿼리 파라미터가 없어(GET /api/contests 는
// page/page_size 뿐) 서버 컴포넌트가 전체를 받아와 직접 좁히고 정렬한다 — 그래도
// "서버가 렌더링한다"는 인수조건은 그대로 지켜진다: 브라우저는 다시 요청하지
// 않는다. page_size 를 넉넉히 크게 주어 한 번에 다 받는다 — 이 플랫폼은 순수
// 콘테스트라 동시에 열린 공모전 수가 페이지네이션이 필요할 규모가 아니다
// (검증되지 않으면 이 값을 늘리거나 다시 페이지네이션을 도입한다).
const LIST_PAGE_SIZE = 200;

export async function fetchContests(): Promise<Contest[]> {
  const res = await backendClient.GET("/api/contests", {
    params: { query: { page: 1, page_size: LIST_PAGE_SIZE } },
  });

  if (!res.response.ok) {
    throw new Error(`GET /api/contests 실패: ${res.response.status} ${res.response.statusText}`);
  }
  if (res.data === undefined) {
    throw new Error("GET /api/contests: 2xx 인데 응답 본문이 비어 있다");
  }
  return res.data.items;
}

export async function fetchDeliverableTypes(): Promise<DeliverableType[]> {
  const res = await backendClient.GET("/api/contests/deliverable-types");

  if (!res.response.ok) {
    throw new Error(
      `GET /api/contests/deliverable-types 실패: ${res.response.status} ${res.response.statusText}`,
    );
  }
  if (res.data === undefined) {
    throw new Error("GET /api/contests/deliverable-types: 2xx 인데 응답 본문이 비어 있다");
  }
  return res.data;
}

export async function fetchContestCategories(): Promise<Category[]> {
  const res = await backendClient.GET("/api/contests/categories");

  // `res.error` 만 보고 판정하면 안 된다. openapi-fetch 는 응답 본문이 비어
  // 있으면(Content-Length: 0, HEAD, 204) 실패 응답이어도 `error` 를 그냥
  // `undefined` 로 둔다(node_modules/openapi-fetch/dist/index.js 의 "handle
  // empty content" 분기) — 프록시가 삼킨 502, 본문 없는 401/504가 전부 여기
  // 해당한다. `if (res.error)` 만 보면 그 경우를 놓치고 `res.data` 인
  // `undefined` 를 `Category[]` 인 척 그대로 돌려주게 되고, 호출부는 한참
  // 떨어진 곳에서 `.map is not a function` 같은 TypeError 로 터진다. 그래서
  // 항상 채워지는 `res.response.status` 를 먼저 본다.
  //
  // 이 클라이언트는 이후 화면들이 그대로 베낄 모양이고, BFF 프록시(FE-08,
  // #32)를 거치기 시작하면 빈 본문 502/504가 흔해지므로 여기서부터 상태
  // 코드를 우선으로 판정한다.
  if (!res.response.ok) {
    throw new Error(
      `GET /api/contests/categories 실패: ${res.response.status} ${res.response.statusText}`,
    );
  }

  // 상태는 2xx인데 본문이 비어 있는 경우(204 등)도 같은 이유로 놓치면 안
  // 된다 — 이 엔드포인트는 항상 배열을 문서화하고 있으므로 이 분기는 그
  // 계약을 런타임에서도 지키는 방어선이다. 부수 효과로, `res.data` 를
  // `undefined` 로 좁혀 그 다음 `return res.data` 가 `Category[] | undefined`
  // 가 아니라 `Category[]` 로 타입 체크를 통과한다.
  if (res.data === undefined) {
    throw new Error("GET /api/contests/categories: 2xx 인데 응답 본문이 비어 있다");
  }
  return res.data;
}
