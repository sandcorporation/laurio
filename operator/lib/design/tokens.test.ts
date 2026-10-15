// 운영자 앱의 디자인 토큰은 공개 앱의 것과 **같아야 한다** (#422, 부모 #421).
//
// 세 앱이 같은 브랜드를 입는데 토큰 파일은 앱마다 하나씩이다(강의실이 먼저
// 세운 방식, #298). 공유 패키지로 빼지 않은 이유는 손으로 관리되는 목록 셋
// (Dockerfile 의 COPY, compose 의 node_modules 볼륨)이 또 늘고 **로컬 게이트가
// 그 셋을 보지 못하기 때문**이다(#166이 그렇게 CI 를 4잡 빨갛게 냈다).
//
// 대신 복사하고, **갈라지는 것을 기계가 막는다** — `classroom/lib/design/
// tokens.test.ts`와 같은 모양이다. 한쪽을 고치면 이 테스트가 빨개지고, 그때
// 양쪽을 같이 고치면 된다.
import * as fs from "node:fs";
import * as path from "node:path";

import { describe, expect, it } from "vitest";

const OPERATOR = path.resolve(__dirname, "..", "..", "app", "tokens.css");
const PUBLIC_APP = path.resolve(__dirname, "..", "..", "..", "frontend", "app", "tokens.css");

describe("디자인 토큰은 공개 앱과 한 벌이다 (#422)", () => {
  it("두 파일을 실제로 찾는다 — 경로가 바뀌면 이 검사가 조용히 빈손이 된다", () => {
    expect(fs.existsSync(OPERATOR), OPERATOR).toBe(true);
    expect(fs.existsSync(PUBLIC_APP), PUBLIC_APP).toBe(true);
  });

  it("내용이 한 글자도 다르지 않다", () => {
    expect(
      fs.readFileSync(OPERATOR, "utf8"),
      "operator/app/tokens.css 가 frontend/app/tokens.css 와 갈렸다 — " +
        "한쪽만 고쳤다면 다른 쪽도 같이 고친다.",
    ).toBe(fs.readFileSync(PUBLIC_APP, "utf8"));
  });

  // 본문(Pretendard)과 등폭(IBM Plex Mono, #743)을 다 센다 — 등폭도 저장소 안의
  // 파일이라 한쪽만 갈아끼우면 코드 블록의 글꼴이 갈린다.
  it.each([
    "PretendardVariable.woff2",
    "IBMPlexMono-Regular.woff2",
    "IBMPlexMono-Medium.woff2",
    "IBMPlexMono-SemiBold.woff2",
  ])("서체 파일 %s 도 같다 — 한쪽만 갈아끼우면 서브도메인마다 글꼴이 갈린다", (name) => {
    const a = path.resolve(__dirname, "..", "..", "app", "fonts", name);
    const b = path.resolve(__dirname, "..", "..", "..", "frontend", "app", "fonts", name);
    expect(fs.readFileSync(a).equals(fs.readFileSync(b))).toBe(true);
  });
});
