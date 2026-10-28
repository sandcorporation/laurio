import { describe, expect, it } from "vitest";

import { gradabilityWarningLine, stashWarnings, takeWarnings } from "./gradability";

function memoryStorage() {
  const map = new Map<string, string>();
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
  };
}

describe("gradability", () => {
  it("경고 한 줄은 「~일 수 있다」 어조다", () => {
    expect(gradabilityWarningLine("배포 주소나 외부 서비스에 접속해야 한다")).toContain("확인하지 못할 수 있습니다");
  });

  it("만들기 화면이 건넨 경고는 한 번만 읽힌다", () => {
    const s = memoryStorage();
    const w = [{ checklist_item_id: 3, text: "실제로 이동한다", reason: "실제 실행 결과를 봐야 한다" }];
    stashWarnings(s, 7, w);
    expect(takeWarnings(s, 7)).toEqual(w);
    expect(takeWarnings(s, 7)).toEqual([]);
  });

  it("경고가 없으면 아무것도 건네지 않고, 깨진 값은 빈 목록이다", () => {
    const s = memoryStorage();
    stashWarnings(s, 1, []);
    expect(takeWarnings(s, 1)).toEqual([]);
    s.setItem("codemit:gradability:2", "{not json");
    expect(takeWarnings(s, 2)).toEqual([]);
  });
});
