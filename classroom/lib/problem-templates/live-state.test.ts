// 내린 뒤 새로고침 없이 다시 공개할 수 있어야 한다(2026-09-16 사용자 보고).
// 버그는 「내려간 템플릿을 살아 있는 것으로 셌다」 하나였고, 그 판단이 이제 이
// 함수에 있다.
import { describe, expect, it } from "vitest";

import { liveTemplateFrom } from "./live-state";

describe("liveTemplateFrom", () => {
  it("공개 응답은 공유 코드를 남긴다 — 공개 폼이 감춰진다", () => {
    expect(liveTemplateFrom({ share_code: "abc123", taken_down: false })).toEqual({
      shareCode: "abc123",
    });
  });

  it("**내려간 템플릿은 없는 것과 같다** — 공개 폼이 돌아온다", () => {
    // 이 한 줄이 그 버그였다: 예전에는 `{share_code, taken_down: true}` 를 그대로
    // 들고 있어서 「null 이 아니다」가 참이 되어 폼이 끝까지 돌아오지 않았다.
    expect(liveTemplateFrom({ share_code: "abc123", taken_down: true })).toBeNull();
  });

  it("공개한 적이 없으면 null 이다", () => {
    expect(liveTemplateFrom(null)).toBeNull();
    expect(liveTemplateFrom(undefined)).toBeNull();
  });

  it("상세 응답의 요약처럼 `taken_down` 칸이 없으면 살아 있는 것이다", () => {
    // 백엔드는 상세에 **살아 있는 것만** 싣고 아니면 null 이라(`_live_problem_template`)
    // 그 요약에는 이 칸이 없다 — 없는 것을 「내려갔다」로 읽으면 공개한 템플릿이
    // 새로고침마다 사라진다.
    expect(liveTemplateFrom({ share_code: "abc123" })).toEqual({ shareCode: "abc123" });
  });

  it("공개 → 내리기 → 다시 공개가 폼이 뜬 상태를 거쳐 돈다", () => {
    const published = liveTemplateFrom({ share_code: "first", taken_down: false });
    const takenDown = liveTemplateFrom({ share_code: "first", taken_down: true });
    const republished = liveTemplateFrom({ share_code: "second", taken_down: false });

    expect(published).not.toBeNull();
    // 여기서 폼이 떠야 다시 공개할 수 있다.
    expect(takenDown).toBeNull();
    // 재공개는 **새 공유 코드**다(백엔드가 새 템플릿 행을 만든다) — 옛 코드가
    // 남아 있으면 죽은 주소를 전달하게 된다.
    expect(republished).toEqual({ shareCode: "second" });
  });
});
