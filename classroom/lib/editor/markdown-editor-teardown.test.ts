// Toast UI 에디터는 React 가 DOM 을 떼어 내기 **전에** 부숴야 한다 (GlitchTip 오류 26).
//
// **prod 에서 실제로 났다.** 강사가 문제 화면(설명 에디터가 떠 있다)에서 「제출」
// 등으로 다른 화면에 가면, 200ms 뒤 `NotFoundError: Failed to execute 'removeChild'
// on 'Node'` 가 uncaught 로 떴다(오류 8건, 전부 강의실 앱). 원인은 라이브러리의
// 툴바다 — `Toolbar.addEvent` 가 `ResizeObserver` 콜백을 200ms 스로틀
// (`tui-code-snippet` throttle, 트레일링 호출이 `setTimeout` 이다)로 감싸는데,
// React 가 에디터 컨테이너를 문서에서 떼면 그 옵저버가 「크기 0」으로 한 번 불리고,
// 그 트레일링 호출이 `destroy()` 뒤에 흘러 이미 없는 노드를 지우려다 던진다.
// `destroy()` 를 `try` 로 감싸도 소용없다 — 던지는 곳은 우리 호출 스택이 아니라
// 라이브러리의 타이머다.
//
// **순서만 바꾸면 사라진다.** `useEffect` 의 정리는 DOM 을 떼어 낸 **뒤에**(대개 한
// 프레임 뒤, 옵저버가 이미 불린 뒤) 돌고, `useLayoutEffect` 의 정리는 React 가 호스트
// 노드를 떼어 내기 **전에** 커밋 안에서 돈다 — 그때 `destroy()` 가 옵저버를 끊으면
// 트레일링 호출이 예약될 길이 없다. 실제 컴포넌트를 React 19 로 언마운트하는 브라우저
// 루프에서 `useEffect` 는 5/5 던지고, `useLayoutEffect` 는 0/5 였다.
//
// 이 앱의 단위 시임은 node 환경의 순수 함수뿐이라(컴포넌트 테스트를 두지 않는다,
// ADR-0017/0021) `runtime-config.test.ts` 처럼 **구조**를 본다: `destroy()` 를 부르는
// 훅이 `useLayoutEffect` 인가.
import * as fs from "node:fs";
import * as path from "node:path";

import { describe, expect, it } from "vitest";

const SOURCE = fs.readFileSync(
  path.resolve(__dirname, "..", "..", "app", "components", "MarkdownEditor.tsx"),
  "utf8",
);

describe("MarkdownEditor 정리 순서", () => {
  it("에디터를 부수는 정리는 useLayoutEffect 안에 있다 — DOM 을 떼기 전에 돈다", () => {
    const destroyAt = SOURCE.indexOf(".destroy()");
    expect(destroyAt, "MarkdownEditor 가 더 이상 destroy() 를 부르지 않는다").toBeGreaterThan(-1);

    const hooks = [...SOURCE.slice(0, destroyAt).matchAll(/\b(useLayoutEffect|useEffect)\(/g)];
    const enclosing = hooks.at(-1)?.[1];
    expect(enclosing).toBe("useLayoutEffect");
  });
});
