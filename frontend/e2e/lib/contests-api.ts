// 공모전 준비를 화면 없이 API 로 깐다(2026-10-02) — 시험 하나는 3초 안에 끝나야 하는데,
// 개최 폼을 화면으로 채우는 데만 2초가 들었다. 폼 자체는 `payment.spec.ts` 의 한 시험이
// 화면으로 걷고, 나머지는 여기서 초안을 받아 자기 대상(결제 화면 등)부터 본다.
//
// 호출은 전부 `page.context().request` 로 한다 — 브라우저와 쿠키를 공유하고, Origin 은
// 손으로 싣는다(`contest-images.spec.ts` 상단 주석).

import { expect } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { publicOrigin } from "./session";

export async function findIdByName(request: APIRequestContext, path: string, name: string): Promise<number> {
  const res = await request.get(path);
  const list = (await res.json()) as { id: number; name: string }[];
  const found = list.find((item) => item.name === name);
  expect(found, `"${name}"을(를) ${path}에서 찾지 못했다`).toBeTruthy();
  return (found as { id: number }).id;
}

/** 게임·웹 서비스 초안 공모전 하나를 만들고 id 를 돌려준다. */
export async function createDraftContest(page: Page, title: string, prize = 5_000_000): Promise<number> {
  const api = page.context().request;
  const [categoryId, deliverableTypeId] = await Promise.all([
    findIdByName(api, "/api/backend/contests/categories", "게임"),
    findIdByName(api, "/api/backend/contests/deliverable-types", "웹 서비스"),
  ]);
  const created = await api.post("/api/backend/contests", {
    headers: { origin: publicOrigin() },
    data: {
      title,
      category_id: categoryId,
      deliverable_type_ids: [deliverableTypeId],
      description: "",
      prize,
      deadline_at: new Date(Date.now() + 10 * 24 * 60 * 60 * 1000).toISOString(),
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).id as number;
}
