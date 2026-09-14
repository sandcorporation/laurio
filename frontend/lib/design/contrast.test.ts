// 대비 검사(#397, spec #396 「사용자로서, 다크에서도 본문 글자·흐린 보조
// 글자·통과 초록·주의 빨강이 모두 읽기 쉬운 대비를 갖길 원한다」).
//
// `tokens.css` 를 텍스트로 읽어 라이트·다크 두 벌의 주요 조합이 WCAG AA
// (4.5:1) 를 넘는지 계산한다 — 컴포넌트를 그리지 않고 산출물(토큰 파일)만
// 본다(브랜드 가드·토큰 동일성 검사와 같은 방식).
//
// 두 앱의 `tokens.css` 는 한 글자도 다르지 않다(`classroom/lib/design/
// tokens.test.ts`) — 그래서 여기서는 frontend 쪽 하나만 읽는다.
import * as fs from "node:fs";
import * as path from "node:path";

import { describe, expect, it } from "vitest";

import { blendOver, contrastRatio, parseTokenPalette, type Rgb } from "./contrast";

const TOKENS_PATH = path.resolve(__dirname, "..", "..", "app", "tokens.css");
const MIN_CONTRAST = 4.5;
const DIM_ALPHA = 0.6; // text-ink/60

describe("다크·라이트 토큰의 대비는 WCAG AA 를 넘는다 (#397)", () => {
  it("토큰 파일을 실제로 찾는다 — 경로가 바뀌면 이 검사가 조용히 빈손이 된다", () => {
    expect(fs.existsSync(TOKENS_PATH), TOKENS_PATH).toBe(true);
  });

  const css = fs.readFileSync(TOKENS_PATH, "utf8");
  const palette = parseTokenPalette(css);

  for (const theme of ["light", "dark"] as const) {
    const ink = palette.ink[theme];
    const paper = palette.paper[theme];
    const surface = palette.surface[theme];
    const attention = palette.attention[theme];
    const verified = palette.verified[theme];
    const dimInk = blendOver(ink, surface, DIM_ALPHA);

    const combos: Array<[string, Rgb, Rgb]> = [
      ["본문 글자 / 바탕 (ink/paper)", ink, paper],
      ["본문 글자 / 뜬 면 (ink/surface)", ink, surface],
      ["흐린 글자 60% / 뜬 면 (ink/60 위 surface)", dimInk, surface],
      ["주 버튼 글자 / 바탕 (paper 글자, ink 바탕)", paper, ink],
      ["통과 초록 / 뜬 면 (verified/surface)", verified, surface],
      ["주의 빨강 / 뜬 면 (attention/surface)", attention, surface],
    ];

    for (const [label, fg, bg] of combos) {
      it(`${theme} — ${label} 가 4.5:1 이상이다`, () => {
        const ratio = contrastRatio(fg, bg);
        expect(ratio, `${label} 대비비 ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(MIN_CONTRAST);
      });
    }
  }

  it("검사 자체가 살아 있다 — 대비가 모자란 가짜 값은 실제로 잡힌다", () => {
    // 거의 같은 두 회색 — 눈으로도 구별이 안 되는 값이다.
    const almostSame = contrastRatio({ r: 120, g: 120, b: 120 }, { r: 130, g: 130, b: 130 });
    expect(almostSame).toBeLessThan(MIN_CONTRAST);
  });

  it("파싱도 살아 있다 — light-dark() 가 없는 색은 파싱이 실패로 알린다", () => {
    expect(() => parseTokenPalette("@theme { --color-ink: #17160f; }")).toThrow();
  });
});
