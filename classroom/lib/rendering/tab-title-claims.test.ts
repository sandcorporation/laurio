import { describe, expect, it } from "vitest";

import { createTabTitleClaims } from "./tab-title-claims";

/** 쓰기마다 감시자를 부르는 가짜 문서 — 두 곳이 서로 덮어쓰면 쓰기 한도를 넘겨 터진다. */
function fakeDocument() {
  const state = { title: "", writes: 0, watchers: new Set<() => void>() };
  const claim = createTabTitleClaims({
    read: () => state.title,
    write: (title) => {
      if (++state.writes > 20) throw new Error("제목을 끝없이 덮어쓴다");
      state.title = title;
      state.watchers.forEach((watcher) => watcher());
    },
    watch: (onChange) => {
      state.watchers.add(onChange);
      return () => state.watchers.delete(onChange);
    },
  });
  const outside = (title: string) => {
    state.title = title;
    state.watchers.forEach((watcher) => watcher());
  };
  return { state, claim, outside };
}

describe("탭 제목 맡기기(#1406)", () => {
  it("안내 제목은 화면이 나중에 맡겨도 이기고, 감시자는 하나다", () => {
    const { state, claim } = fakeDocument();
    claim("안내", true);
    claim("새 문제");
    expect(state.title).toBe("안내");
    expect(state.watchers.size).toBe(1);
  });

  it("바깥이 제목을 바꾸면 이긴 제목을 되돌려 놓는다(#1400)", () => {
    const { state, claim, outside } = fakeDocument();
    claim("알림");
    outside("Codemit 클래스");
    expect(state.title).toBe("알림");
  });

  it("안내가 사라지면 화면 제목으로 돌아가고, 다 거두면 감시를 끊는다", () => {
    const { state, claim } = fakeDocument();
    const releasePage = claim("새 문제");
    const releaseNotice = claim("안내", true);
    releaseNotice();
    expect(state.title).toBe("새 문제");
    releasePage();
    expect(state.watchers.size).toBe(0);
  });
});
