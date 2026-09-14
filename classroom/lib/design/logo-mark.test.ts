// 로고 원본은 공개 앱에 있고, 강의실은 복사본을 둔다(#392, #391 Implementation
// Decisions 「로고 원본」) — `tokens.test.ts`(#298)와 같은 방식이다. 공유
// 패키지로 빼지 않는 이유도 같다(손으로 관리되는 목록 셋이 또 늘고 로컬
// 게이트가 그것을 못 본다, #166).
//
// 대상은 심볼 자체(`components/logo-mark.tsx`)와 그것을 쓰는 두 아이콘 라우트
// (`icon.tsx`·`apple-icon.tsx`)다. 운영자 앱은 주의색 타일로 **일부러** 다르므로
// (#391 — "운영자 앱만 주의색 타일로 구별한다") 이 비교에 들지 않는다.
import * as fs from "node:fs";
import * as path from "node:path";

import { describe, expect, it } from "vitest";

const CLASSROOM_APP = path.resolve(__dirname, "..", "..", "app");
const PUBLIC_APP = path.resolve(__dirname, "..", "..", "..", "frontend", "app");

const COPIES = [
  { name: "components/logo-mark.tsx", label: "로고 심볼" },
  { name: "icon.tsx", label: "파비콘" },
  { name: "apple-icon.tsx", label: "홈 화면 추가 아이콘" },
];

describe("로고 복사본은 공개 앱과 한 벌이다 (#392)", () => {
  for (const { name, label } of COPIES) {
    const classroomFile = path.join(CLASSROOM_APP, name);
    const publicFile = path.join(PUBLIC_APP, name);

    it(`${label} — 두 파일을 실제로 찾는다`, () => {
      expect(fs.existsSync(classroomFile), classroomFile).toBe(true);
      expect(fs.existsSync(publicFile), publicFile).toBe(true);
    });

    it(`${label} — 내용이 한 글자도 다르지 않다`, () => {
      expect(
        fs.readFileSync(classroomFile, "utf8"),
        `classroom/app/${name} 이 frontend/app/${name} 와 갈렸다 — 한쪽만 고쳤다면 다른 쪽도 같이 고친다.`,
      ).toBe(fs.readFileSync(publicFile, "utf8"));
    });
  }
});
