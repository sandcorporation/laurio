import { describe, expect, it } from "vitest";

import {
  attemptEntryLabel,
  buildEntryPayload,
  entryBlockedReason,
  initialEntryState,
  requiredWithoutEvidence,
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

  it("빈 근거와 빈 선택 자료는 빼고 싣는다", () => {
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

describe("entryBlockedReason", () => {
  it("동의가 먼저, 그다음 바꾸기 확인", () => {
    const f = form({ has_entry: true });
    const state = { ...initialEntryState(f), on: true };
    expect(entryBlockedReason(f, state)).toContain("동의");
    expect(entryBlockedReason(f, { ...state, consent: true })).toContain("바뀐다");
    expect(entryBlockedReason(f, { ...state, consent: true, replaceConfirmed: true })).toBeNull();
  });
});

describe("requiredWithoutEvidence", () => {
  it("근거 없는 필수 요구사항을 고른다", () => {
    const f = form();
    expect(requiredWithoutEvidence(f, initialEntryState(f)).map((r) => r.requirement_id)).toEqual([2]);
  });
});

describe("attemptEntryLabel", () => {
  it("결과를 말한다", () => {
    expect(attemptEntryLabel({ status: "entered", reason: "" })).toBe("공모전에도 냈습니다");
    expect(attemptEntryLabel({ status: "rejected", reason: "마감" })).toBe("공모전에는 내지 못했습니다 — 마감");
  });
});
