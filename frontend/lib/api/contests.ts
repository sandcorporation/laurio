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

export async function fetchContestCategories(): Promise<Category[]> {
  const res = await backendClient.GET("/api/contests/categories");
  // 이 엔드포인트는 지금은 200만 문서화되어 있다(schema.gen.ts 의
  // `operations["contests_api_list_categories"]["responses"]` 참고) — 그래서
  // openapi-fetch가 추론하는 `res.error` 의 타입은 `never` 다. `if (res.error)`
  // 로 좁히는 순간 이 분기 자체가 도달 불가로 확정되어 `res` 가 `never` 로
  // 좁혀진다(그래서 이 분기 안에서 `res.error` 를 다시 참조하면 안 된다 — 좁혀진
  // `res` 자체가 `never` 라 `tsc` 가 정당하게 잡아낸다). 백엔드가 이 엔드포인트에
  // 에러 응답을 문서화하면(4xx 등) 이 분기가 실제로 살아나고 `res.data` 는 그
  // 성공 응답 하나로 좁혀진다 — 지금은 그 좁힘 자체가 "항상 성공"이라는 문서화된
  // 계약을 타입 수준에서 강제하는 역할을 한다.
  if (res.error) {
    throw new Error("GET /api/contests/categories 실패");
  }
  return res.data;
}
