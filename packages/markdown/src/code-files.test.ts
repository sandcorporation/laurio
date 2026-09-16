// 코드블록을 파일로 받을 때의 이름 규칙(2026-09-16).
import { describe, expect, it } from "vitest";

import { downloadNameFor, extensionFor, fileBaseFromTitle, fileNameFromMeta } from "./code-files";

describe("확장자", () => {
  it("아는 언어는 그 언어의 확장자로 준다", () => {
    expect(extensionFor("python")).toBe("py");
    expect(extensionFor("Java")).toBe("java");
    expect(extensionFor("csv")).toBe("csv");
    expect(extensionFor("  TEXT ")).toBe("txt");
  });

  it("모르는 언어는 null — 확장자를 지어내지 않는다", () => {
    expect(extensionFor("브레인퍽")).toBeNull();
    expect(extensionFor("")).toBeNull();
  });
});

describe("강사가 적은 파일 이름", () => {
  it("언어 뒤에 적은 이름을 그대로 쓴다", () => {
    expect(fileNameFromMeta("map3-terrain.txt")).toBe("map3-terrain.txt");
    expect(fileNameFromMeta("movies.csv 추가설명")).toBe("movies.csv");
    expect(fileNameFromMeta("지도.txt")).toBe("지도.txt");
  });

  it("경로를 타거나 숨김 파일이 되는 이름은 쓰지 않는다", () => {
    expect(fileNameFromMeta("../../etc/passwd")).toBeNull();
    expect(fileNameFromMeta("/etc/hosts")).toBeNull();
    expect(fileNameFromMeta(".bashrc")).toBeNull();
    expect(fileNameFromMeta("이름 없음")).toBeNull();
    expect(fileNameFromMeta("")).toBeNull();
  });
});

describe("자동으로 짓는 이름", () => {
  it("문제 제목에서 몸통을 짓고 순번과 확장자를 붙인다", () => {
    expect(downloadNameFor({ language: "python", title: "A* 길찾기", index: 2 })).toBe("A-길찾기-2.py");
  });

  it("적은 이름이 있으면 그것이 이긴다", () => {
    expect(downloadNameFor({ language: "text", meta: "map1-small.txt", title: "길찾기", index: 1 })).toBe(
      "map1-small.txt",
    );
  });

  it("모르는 언어면 null — 파일로 주지 않는다", () => {
    expect(downloadNameFor({ language: "", title: "제목", index: 1 })).toBeNull();
  });

  it("제목에 쓸 글자가 없으면 code 로 떨어진다", () => {
    expect(fileBaseFromTitle("!!! ???")).toBe("code");
    expect(downloadNameFor({ language: "json", title: "", index: 3 })).toBe("code-3.json");
  });
});
