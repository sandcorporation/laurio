// 생성된 타입을 실제로 쓰는 예시 호출(FE-03, #28 인수조건).
//
// `GET /api/contests/categories` 는 공개 표면이다(auth=None, ADR-0015) — 로그인
// 없이 카테고리 목록을 내려준다. `Category` 는 `id`(number)·`name`(string) 두
// 필드뿐이라 백엔드 스키마 변화를 눈으로 확인하기 좋은 최소 예시다.
//
// 반환 타입은 100% `@laurio/bff-client/schema` 에서 온다 — 여기서 직접 선언하지 않는다.
// 백엔드가 필드를 지우거나 이름을 바꾸면 `res.data![0].그필드` 를 쓰는 곳마다
// `tsc --noEmit` 이 즉시 실패한다(런타임이 아니라 빌드타임).
import { backendClient } from "./client";
import type { components } from "@laurio/bff-client/schema";

export type Category = components["schemas"]["CategoryOut"];
export type DeliverableType = components["schemas"]["DeliverableTypeOut"];
export type Contest = components["schemas"]["ContestOut"];
export type Requirement = components["schemas"]["RequirementOut"];
export type ContestImage = components["schemas"]["ContestImageOut"];

export type ContestSort = components["schemas"]["ContestSort"];

// 홈이 공모전을 네 묶음으로 큐레이션할 때 쓰는 타입(#94, spec #92). 묶음
// 식별자는 백엔드가 정한 enum — `frontend/lib/home-curation.ts`의 번역표가
// 이 유니온을 `Record`로 받아, 값이 하나 늘면 `tsc --noEmit`이 빌드타임에
// 잡는다.
export type HomeCurationBucket = components["schemas"]["HomeCurationBucket"];
export type HomeCurationGroup = components["schemas"]["HomeCurationGroupOut"];

// 한 페이지에 보여줄 개수. **필터·정렬은 백엔드가 한다**(#39) — 예전에는 이
// 함수가 `page_size=200` 으로 전부 받아와 서버 컴포넌트가 직접 걸렀는데, 두
// 가지로 조용히 틀렸다: 공개 Contest 가 그 수를 넘으면 뒤쪽이 목록에서 그냥
// 사라졌고(예외도 빈 화면도 아니다), 애초에 200 이 오지도 않았다 — ninja 가
// `page_size` 를 `NINJA_MAX_PER_PAGE_SIZE`(기본 100)로 잘라내므로 실제 천장은
// 100 이었다. 이제 필요한 페이지만 받는다.
export const CONTESTS_PAGE_SIZE = 20;

export type ContestListQuery = {
  category?: number;
  deliverableType?: number;
  sort?: ContestSort;
  /** #227 — 기본(false/undefined)은 지금 참가할 수 있는 것만, true면 마감된 것만. */
  closed?: boolean;
  page?: number;
};

export type ContestPage = {
  items: Contest[];
  /** 필터가 걸린 뒤의 전체 건수 — 이 페이지에 담긴 수가 아니다. */
  count: number;
  page: number;
  pageSize: number;
  totalPages: number;
};

export async function fetchContests(query: ContestListQuery = {}): Promise<ContestPage> {
  // 백엔드는 `page` 가 1 미만이면 422 를 낸다. 공개 표면이라 손으로 친 URL
  // (`?page=0`, `?page=-3`)이 오류 화면이 되면 안 되므로 여기서 1 로 맞춘다 —
  // 「알 수 없는 값은 안전한 기본값으로」(#39 인수조건).
  const page = Math.max(1, Math.trunc(query.page ?? 1));

  const res = await backendClient.GET("/api/contests", {
    params: {
      query: {
        category: query.category,
        deliverable_type: query.deliverableType,
        sort: query.sort ?? "deadline",
        closed: query.closed ?? false,
        page,
        page_size: CONTESTS_PAGE_SIZE,
      },
    },
  });

  if (!res.response.ok) {
    throw new Error(`GET /api/contests 실패: ${res.response.status} ${res.response.statusText}`);
  }
  if (res.data === undefined) {
    throw new Error("GET /api/contests: 2xx 인데 응답 본문이 비어 있다");
  }

  return {
    items: res.data.items,
    count: res.data.count,
    page,
    pageSize: CONTESTS_PAGE_SIZE,
    totalPages: Math.max(1, Math.ceil(res.data.count / CONTESTS_PAGE_SIZE)),
  };
}

// 홈의 네 묶음 — 진행중·마감임박·심사중·완료(#94, spec #92). **묶음 판정은
// 백엔드가 한다**: 이 함수는 `contests.api.get_home_curation`이 이미 판정해
// 내려준 값을 그대로 옮길 뿐, `status`·`deadline_at`에서 다시 계산하지 않는다
// — 화면이 재파생하면 새 상태가 조용히 어느 분기에도 안 걸리는 실패를 이
// 저장소가 반복해서 겪었다(#94 인수조건).
//
// 응답은 항상 네 묶음을 다 담는다(빈 묶음도 `contests: []`로 온다) — 그래서
// 호출부는 "묶음이 존재하는지"를 따로 걱정하지 않고 그대로 렌더링할 수 있다.
export async function fetchHomeCuration(): Promise<HomeCurationGroup[]> {
  const res = await backendClient.GET("/api/contests/home");

  if (!res.response.ok) {
    throw new Error(
      `GET /api/contests/home 실패: ${res.response.status} ${res.response.statusText}`,
    );
  }
  if (res.data === undefined) {
    throw new Error("GET /api/contests/home: 2xx 인데 응답 본문이 비어 있다");
  }

  return res.data;
}

// 존재하지 않거나 draft 인 Contest 는 백엔드가 이미 404 로 답한다
// (contests.api.get_contest, _PUBLICLY_VISIBLE_STATUSES) — 여기서는 그 상태 코드를
// null 로 옮겨 호출부(app/contests/[id]/page.tsx)가 `notFound()` 를 부르게 한다.
// 그 외 실패는 여전히 예외로 던져 조용히 묻히지 않게 한다.
export async function fetchContest(id: number): Promise<Contest | null> {
  const res = await backendClient.GET("/api/contests/{contest_id}", {
    params: { path: { contest_id: id } },
  });

  if (res.response.status === 404) {
    return null;
  }
  if (!res.response.ok) {
    throw new Error(
      `GET /api/contests/${id} 실패: ${res.response.status} ${res.response.statusText}`,
    );
  }
  if (res.data === undefined) {
    throw new Error(`GET /api/contests/${id}: 2xx 인데 응답 본문이 비어 있다`);
  }
  return res.data;
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
