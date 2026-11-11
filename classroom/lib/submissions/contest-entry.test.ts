import { describe, expect, it } from "vitest";

import {
  attemptEntryLabel,
  gridEntryLabel,
  instructorEntryBadge,
  buildEntryPayload,
  entryBlockedReason,
  initialEntryState,
  offersContestEntry,
  OPTIONAL_ASSET_LABELS,
  removeOptionalAsset,
  type ContestEntryForm,
} from "./contest-entry";

function form(overrides: Partial<ContestEntryForm> = {}): ContestEntryForm {
  return {
    contest_id: 7,
    accepts_entries: true,
    deadline_at: "2026-10-30T00:00:00Z",
    has_entry: false,
    requirements: [
      { requirement_id: 1, text: "추가", required: true, previous: { is_met: true, note: "됨", evidence: [{ kind: "demo_path", value: "/todos" }] } },
      { requirement_id: 2, text: "삭제", required: true, previous: null },
    ],
    optional_assets: [{ kind: "demo_url", value: "https://todo.example.com", label: "", content_type: "" }],
    upload_target_refs: {},
    require_demo_video: false,
    require_screenshot: false,
    ...overrides,
  };
}

describe("initialEntryState", () => {
  it("직전 제출로 미리 채우고 새 요구사항은 빈칸으로 둔다", () => {
    const state = initialEntryState(form());
    expect(state.responses[1]).toEqual({ isMet: true, note: "됨", evidence: [{ kind: "demo_path", value: "/todos" }] });
    expect(state.responses[2]).toEqual({ isMet: false, note: "", evidence: [] });
    expect(state.optionalAssets).toHaveLength(1);
    expect(state.on).toBe(false);
    expect(state.consent).toBe(false);
  });
});

describe("buildEntryPayload", () => {
  it("스위치가 꺼져 있으면 아무것도 싣지 않는다", () => {
    expect(buildEntryPayload(form(), initialEntryState(form()))).toBeNull();
  });

  it("빈 확인 위치와 빈 선택 자료는 빼고 싣는다", () => {
    const state = { ...initialEntryState(form()), on: true, consent: true };
    state.responses[2] = { isMet: false, note: "", evidence: [{ kind: "screenshot", value: "  " }] };
    state.optionalAssets.push({ kind: "demo_url", value: " ", label: "", content_type: "" });
    const payload = buildEntryPayload(form(), state);
    expect(payload?.requirement_responses[1].evidence).toEqual([]);
    expect(payload?.optional_assets).toHaveLength(1);
    expect(payload?.replace_existing).toBe(false);
  });

  it("이미 낸 제출이 있으면 확인했을 때만 바꾸기를 싣는다", () => {
    const f = form({ has_entry: true });
    const state = { ...initialEntryState(f), on: true, consent: true, replaceConfirmed: true };
    expect(buildEntryPayload(f, state)?.replace_existing).toBe(true);
  });
});

describe("entryBlockedReason required media", () => {
  it("requires a video or screenshot when the contest marks it required", () => {
    const required = form({ require_demo_video: true, require_screenshot: true });
    const state = { ...initialEntryState(required), on: true, consent: true, optionalAssets: [] };
    expect(entryBlockedReason(required, state)).toBe("시연 영상 자료가 필수입니다.");
    expect(entryBlockedReason(required, { ...state, optionalAssets: [{ kind: "video_link", value: "https://youtu.be/abc", label: "", content_type: "" }] })).toBe("스크린샷 자료가 필수입니다.");
    expect(entryBlockedReason(required, { ...state, optionalAssets: [{ kind: "screenshot", value: "key", label: "", content_type: "image/png" }] })).toBe("시연 영상 자료가 필수입니다.");
  });
});

describe("entryBlockedReason", () => {
  it("동의가 먼저, 그다음 바꾸기 확인", () => {
    const f = form({ has_entry: true });
    const state = { ...initialEntryState(f), on: true };
    expect(entryBlockedReason(f, state)).toContain("동의");
    expect(entryBlockedReason(f, { ...state, consent: true })).toContain("바뀐다");
    expect(entryBlockedReason(f, { ...state, consent: true, replaceConfirmed: true })).toBeNull();
  });
});

describe("attemptEntryLabel", () => {
  it("결과를 말한다", () => {
    expect(attemptEntryLabel({ status: "entered", reason: "" })).toBe("공모전에도 냈습니다");
    expect(attemptEntryLabel({ status: "rejected", reason: "마감" })).toBe("공모전에는 내지 못했습니다 — 마감");
  });
});

describe("instructorEntryBadge (#550)", () => {
  it("지금 공모전 제출인 시도를 먼저 가린다", () => {
    expect(instructorEntryBadge({ contest_entry: null, is_current_contest_entry: false })).toBeNull();
    expect(
      instructorEntryBadge({ contest_entry: { status: "entered" }, is_current_contest_entry: true })?.label,
    ).toBe("지금 공모전 제출");
    expect(
      instructorEntryBadge({ contest_entry: { status: "entered" }, is_current_contest_entry: false })?.label,
    ).toBe("공모전에도 냈음");
    expect(
      instructorEntryBadge({ contest_entry: { status: "rejected" }, is_current_contest_entry: false })?.tone,
    ).toBe("attention");
  });
});

describe("gridEntryLabel (#550)", () => {
  it("칸의 공모전 표시를 말한다", () => {
    expect(gridEntryLabel("current")).toContain("지금 공모전 제출");
    expect(gridEntryLabel("entered")).toContain("냈었음");
    expect(gridEntryLabel(null)).toBeNull();
  });
});

describe("offersContestEntry", () => {
  it("공모전이 받는 문제면 연다 — 강사 본인이 보는 중이어도 닫지 않는다", () => {
    expect(offersContestEntry({ contest: { accepts_entries: true } })).toBe(true);
  });
  it("받지 않는 공모전·공모전 문제가 아니면 닫는다", () => {
    expect(offersContestEntry({ contest: { accepts_entries: false } })).toBe(false);
    expect(offersContestEntry({ contest: null })).toBe(false);
    expect(offersContestEntry({})).toBe(false);
  });
});

describe("시연 영상 링크 (#921)", () => {
  const YOUTUBE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
  const link = { kind: "video_link", value: YOUTUBE, label: "", content_type: "" };

  it("자료 목록 라벨이 직접 제출 화면과 같다", () => {
    expect(OPTIONAL_ASSET_LABELS.video_link).toBe("시연 영상 링크");
    expect(OPTIONAL_ASSET_LABELS.demo_url).toBe("데모 URL");
  });

  it("미리 채우기가 영상 링크를 지우지 않고 그대로 싣는다", () => {
    const f = form({ optional_assets: [link] });
    const payload = buildEntryPayload(f, { ...initialEntryState(f), on: true, consent: true });
    expect(payload?.optional_assets).toEqual([link]);
  });

  it("javascript:·사용자 정보가 든 링크는 내기 전에 막는다", () => {
    for (const value of ["javascript:alert(1)", "https://user:pw@example.com/v", "ftp://example.com/v"]) {
      const f = form({ optional_assets: [{ ...link, value }] });
      const state = { ...initialEntryState(f), on: true, consent: true };
      expect(entryBlockedReason(f, state)).toContain("http:// 또는 https://");
    }
    const ok = form({ optional_assets: [link] });
    expect(entryBlockedReason(ok, { ...initialEntryState(ok), on: true, consent: true })).toBeNull();
  });

  it("확인 위치가 가리키는 자료 순번이 자료를 빼고 빈 값을 거를 때 함께 움직인다", () => {
    const f = form({
      optional_assets: [
        { kind: "demo_url", value: "https://todo.example.com", label: "", content_type: "" },
        link,
        { kind: "screenshot", value: "key/shot", label: "a.png", content_type: "image/png" },
      ],
    });
    const base = { ...initialEntryState(f), on: true, consent: true };
    base.responses[2] = { isMet: true, note: "", evidence: [{ kind: "video_timestamp", value: "0:10", asset_index: 2 }] };
    const removed = removeOptionalAsset(base, 0);
    expect(removed.responses[2].evidence[0].asset_index).toBe(1);
    const cleared = removeOptionalAsset(base, 2);
    expect(cleared.responses[2].evidence[0].asset_index).toBeNull();
    const payload = buildEntryPayload(f, removed);
    expect(payload?.requirement_responses[1].evidence[0].asset_index).toBe(1);
  });
});
