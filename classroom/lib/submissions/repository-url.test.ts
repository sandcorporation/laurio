// 공유 패키지(@codemit/bff-client/repository-url)의 판정 — 강의실·공개 앱 제출 화면이 함께 쓴다.
import { describe, expect, it } from "vitest";

import { checkGithubRepositoryUrl } from "@codemit/bff-client/repository-url";

describe("checkGithubRepositoryUrl", () => {
  it("빈 입력은 판정하지 않는다", () => {
    expect(checkGithubRepositoryUrl("   ")).toBeNull();
  });

  it("저장소 주소는 그대로 받는다", () => {
    expect(checkGithubRepositoryUrl("https://github.com/kim/todo-app")).toEqual({
      ok: true,
      url: "https://github.com/kim/todo-app",
    });
  });

  it("끝의 .git·슬래시, http·www 는 같은 저장소라 말없이 고친다", () => {
    for (const raw of [
      "https://github.com/kim/todo-app.git",
      "https://github.com/kim/todo-app/",
      "https://github.com/kim/todo-app.git/",
      "http://github.com/kim/todo-app",
      "https://www.github.com/kim/todo-app",
      "  https://github.com/kim/todo-app  ",
    ]) {
      expect(checkGithubRepositoryUrl(raw)).toEqual({ ok: true, url: "https://github.com/kim/todo-app" });
    }
  });

  it("SSH 주소는 거부하고 https 주소를 제안한다", () => {
    for (const raw of ["git@github.com:kim/todo-app.git", "ssh://git@github.com/kim/todo-app.git"]) {
      const result = checkGithubRepositoryUrl(raw);
      expect(result?.ok).toBe(false);
      if (result && !result.ok) {
        expect(result.message).toContain("SSH");
        expect(result.suggestion).toBe("https://github.com/kim/todo-app");
      }
    }
  });

  it("파일·브랜치 주소는 거부하고 저장소 주소를 제안한다", () => {
    const result = checkGithubRepositoryUrl("https://github.com/kim/todo-app/tree/main/src");
    expect(result).toEqual({
      ok: false,
      message: expect.stringContaining("저장소 주소만"),
      suggestion: "https://github.com/kim/todo-app",
    });
  });

  it("GitHub 이 아니거나 저장소 이름이 없으면 제안 없이 거부한다", () => {
    for (const raw of ["https://gitlab.com/kim/todo-app", "https://github.com/kim", "kim/todo-app"]) {
      expect(checkGithubRepositoryUrl(raw)).toEqual({
        ok: false,
        message: expect.stringContaining("GitHub 저장소 주소만"),
        suggestion: null,
      });
    }
  });
});
