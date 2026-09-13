import { describe, expect, it } from "vitest";

import {
  INPUT_CLASS,
  badgeClass,
  buttonClass,
  noteClass,
  type BadgeTone,
  type ButtonTone,
} from "./classnames";

// 이 브랜드의 색은 정확히 여섯이다(app/tokens.css) — 이 파일이 그 밖의 이름을
// 부르면 Tailwind 는 조용히 아무 것도 만들지 않는다(#366). 유틸리티마다
// "이름-토큰" 또는 "이름-토큰/투명도" 모양만 허용한다.
const DEFINED_COLOR_TOKENS = ["ink", "paper", "surface", "rule", "attention", "verified"];

// bg-/text-/border- 뒤가 항상 색인 것은 아니다(text-sm 은 크기, border-b 는
// 변(side) 축약이다) — 이 파일이 실제로 쓰는 비색 접미사만 허용 목록에 둔다.
const NON_COLOR_SUFFIXES = new Set(["sm", "xs", "base", "lg", "xl", "none"]);

function assertOnlyDefinedTokens(cls: string) {
  const matches = [...cls.matchAll(/\b(?:bg|text|border)-([a-z]+)(?:\/\d+)?\b/g)];
  for (const [, token] of matches) {
    if (NON_COLOR_SUFFIXES.has(token)) continue;
    expect(DEFINED_COLOR_TOKENS, `정의되지 않은 색 이름을 부른다: ${token} (in "${cls}")`).toContain(token);
  }
}

// 이 브랜드는 각진 모서리(0–2px)를 쓴다 — 토큰이 정한 반경 스케일을 우회하는
// 임의값 클래스(`rounded-[…]`)가 여기 있으면 안 된다.
function assertNoArbitraryRadius(cls: string) {
  expect(cls).not.toMatch(/rounded-\[/);
}

describe("buttonClass", () => {
  const TONES: ButtonTone[] = ["primary", "secondary", "danger", "dangerFilled"];

  it.each(TONES)("%s 톤의 클래스를 고정한다", (tone) => {
    const cls = buttonClass(tone);
    expect(cls).toMatchSnapshot();
    assertOnlyDefinedTokens(cls);
    assertNoArbitraryRadius(cls);
  });

  it("기본값은 secondary/md 다", () => {
    expect(buttonClass()).toBe(buttonClass("secondary", "md"));
  });

  it("primary 는 배경 없는 흰 글자가 아니다 — bg 와 text 를 함께 낸다(#366)", () => {
    const cls = buttonClass("primary");
    expect(cls).toContain("bg-ink");
    expect(cls).toContain("text-paper");
  });

  it("danger 는 테두리만, dangerFilled 는 배경까지 채운다", () => {
    // hover:bg-attention/5 는 danger 에도 있다 — 기본(비-hover) bg-attention 토큰만 본다.
    expect(buttonClass("danger").split(" ")).not.toContain("bg-attention");
    expect(buttonClass("dangerFilled").split(" ")).toContain("bg-attention");
  });

  it("sm 은 md 보다 좁은 패딩을 쓴다", () => {
    expect(buttonClass("secondary", "sm")).toContain("px-3");
    expect(buttonClass("secondary", "md")).toContain("px-4");
  });
});

describe("badgeClass", () => {
  const TONES: BadgeTone[] = ["neutral", "attention", "verified"];

  it.each(TONES)("%s 톤의 클래스를 고정한다", (tone) => {
    const cls = badgeClass(tone);
    expect(cls).toMatchSnapshot();
    assertOnlyDefinedTokens(cls);
  });
});

describe("noteClass", () => {
  it("neutral 과 attention 이 서로 다른 괘선색을 낸다", () => {
    expect(noteClass("neutral")).toContain("border-rule");
    expect(noteClass("attention")).toContain("border-attention");
  });

  it("두 톤 다 면을 칠하지 않는다 — 배경은 surface 뿐이다", () => {
    expect(noteClass("neutral")).not.toMatch(/bg-(?:ink|attention|verified)\b/);
    expect(noteClass("attention")).not.toMatch(/bg-(?:ink|attention|verified)\b/);
    assertOnlyDefinedTokens(noteClass("neutral"));
    assertOnlyDefinedTokens(noteClass("attention"));
  });
});

describe("INPUT_CLASS", () => {
  it("괘선·표면·잉크 토큰만 쓴다", () => {
    assertOnlyDefinedTokens(INPUT_CLASS);
  });
});
