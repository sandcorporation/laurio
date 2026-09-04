import { expect, test } from "@playwright/test";

import { fetchContestCategories } from "@/lib/api/contests";

// FE-03(#28) 인수조건 — "타입이 실제로 쓰이는 예시 호출이 하나 이상 있고 타입
// 체크를 통과한다"를 실행으로도 증명한다. `fetchContestCategories` 는
// `@laurio/bff-client/schema`(백엔드 OpenAPI 스키마에서 생성) 의 타입만으로 응답을
// 해석한다. 이 파일 자체가 `tsc --noEmit` 대상이므로(ADR-0017 — e2e도 타입체크
// 대상), 백엔드 스키마가 바뀌어 `Category` 의 필드가 사라지거나 이름이 바뀌면
// 빌드가 여기서 먼저 죽는다.
//
// dev compose 가 fake 어댑터로 실제로 떠 있어야 한다(ADR-0017 — 모킹하지 않는다).
// `GET /api/contests/categories` 는 공개 표면(auth=None)이라 로그인 없이 바로
// 부를 수 있다. Next 를 거치지 않고 백엔드에 직접 붙는다 — 이 호출은
// 서버 컴포넌트가 쓸 자리이지 BFF 프록시(#32) 대상이 아니다(ADR-0015).
test("생성된 타입으로 공개 카테고리 목록을 실제로 가져온다", async () => {
  const categories = await fetchContestCategories();

  expect(Array.isArray(categories)).toBe(true);
  for (const category of categories) {
    expect(typeof category.id).toBe("number");
    expect(typeof category.name).toBe("string");
  }
});
