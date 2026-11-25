import { describe, expect, it } from "vitest";

import type { NotificationRow } from "../notifications/api";
import { describeNotification } from "../notifications/format";

import { coInstructorCardHint, modelRejectedNote, scoringBlockNote } from "./scoring-block-note";

const connected = {
  archived: false,
  has_openai_key: true,
  openai_key_status: "verified" as const,
  scoring_quota_exhausted: false,
  scoring_server_unreachable: false,
  scoring_connection_kind: "openai_key",
  openai_key_masked: "sk-…7f2a",
  scoring_server_host: null,
  role: "owner" as const,
};

const missing = {
  ...connected,
  has_openai_key: false,
  openai_key_status: null,
  openai_key_masked: null,
};

describe("scoringBlockNote — 제출 현황", () => {
  it("연결 없음 — 「연결 없음」 알림과 같은 원인·동사, 단추도 「넣기」", () => {
    const note = scoringBlockNote(missing, "submissions");

    expect(note).toEqual({
      message:
        "채점 연결이 없어 참여자의 제출이 채점되지 않고 있습니다 — 클래스 설정에서 채점 키를 넣으면 밀린 제출부터 채점됩니다.",
      actionLabel: "클래스 설정에서 넣기",
    });
  });

  it("연결 없음 — 문장이 알림 문구에 그대로 들어 있다", () => {
    const alert = describeNotification({
      notification_type: "classroom_scoring_key_missing",
      context: { class_name: "알고리즘 1반" },
    } as unknown as NotificationRow);

    expect(alert).toContain(scoringBlockNote(missing, "submissions").message);
  });

  it("보관된 클래스도 같은 원인을 말한다", () => {
    expect(scoringBlockNote({ ...missing, archived: true }, "submissions")).toEqual(
      scoringBlockNote(missing, "submissions"),
    );
  });

  it.each([
    [
      "거부됨",
      { openai_key_status: "rejected" as const },
      "채점 키가 거부되어 채점이 멈췄습니다 — 클래스 설정에서 새 키를 저장해 주세요.",
      "클래스 설정에서 저장하기",
    ],
    [
      "크레딧 소진",
      { scoring_quota_exhausted: true },
      "채점 키의 크레딧이 떨어져 채점이 멈췄습니다 — 충전하면 밀린 제출부터 이어서 채점됩니다.",
      "클래스 설정 열기",
    ],
    [
      "서버 연결 불가",
      { scoring_server_unreachable: true },
      "채점 서버에 닿지 않아 채점이 멈췄습니다 — 서버가 다시 열리면 밀린 제출부터 이어서 채점됩니다.",
      "클래스 설정 열기",
    ],
    // 클래스 정보를 읽은 뒤에 연결이 멈춘 경우 — 원인을 지어내지 않는다.
    ["원인 모름", {}, "채점이 멈춰 있습니다 — 클래스 설정에서 채점 연결을 확인해 주세요.", "클래스 설정 열기"],
  ])("%s", (_, patch, message, actionLabel) => {
    expect(scoringBlockNote({ ...connected, ...patch }, "submissions")).toEqual({ message, actionLabel });
  });
});

describe("scoringBlockNote — 완성도 채점", () => {
  it.each([
    ["연결 없음", missing, "채점 연결이 없어 채점할 수 없습니다 — 클래스 설정에서 채점 키를 넣어 주세요."],
    [
      "거부됨",
      { ...connected, openai_key_status: "rejected" as const },
      "채점 키가 거부되어 채점할 수 없습니다 — 클래스 설정에서 새 키를 저장해 주세요.",
    ],
    [
      "크레딧 소진",
      { ...connected, scoring_quota_exhausted: true },
      "채점 키의 크레딧이 떨어져 채점할 수 없습니다 — 충전해 주세요.",
    ],
    [
      "서버 연결 불가",
      { ...connected, scoring_server_unreachable: true },
      "채점 서버에 닿지 않아 채점할 수 없습니다 — 서버가 다시 열리면 채점할 수 있습니다.",
    ],
    ["클래스 정보를 못 읽음", null, "지금은 채점할 수 없습니다 — 클래스 설정에서 채점 연결을 확인해 주세요."],
    ["원인 모름", connected, "지금은 채점할 수 없습니다 — 클래스 설정에서 채점 연결을 확인해 주세요."],
  ])("%s", (_, classroom, message) => {
    const note = scoringBlockNote(classroom, "quality");

    expect(note.message).toBe(message);
    expect(note.actionLabel).toBe(scoringBlockNote(classroom, "submissions").actionLabel);
  });
});

describe("scoringBlockNote — 공동 강사(#1421)", () => {
  const co = { role: "co_instructor" as const };

  it.each([
    [
      "연결 없음",
      { ...missing, ...co },
      "채점 연결이 없어 참여자의 제출이 채점되지 않고 있습니다 — 소유자에게 채점 키를 넣어 달라고 하세요.",
      "채점 연결이 없어 채점할 수 없습니다 — 소유자에게 채점 키를 넣어 달라고 하세요.",
    ],
    [
      "거부됨",
      { ...connected, ...co, openai_key_status: "rejected" as const },
      "채점 키가 거부되어 채점이 멈췄습니다 — 소유자에게 새 키를 저장해 달라고 하세요.",
      "채점 키가 거부되어 채점할 수 없습니다 — 소유자에게 새 키를 저장해 달라고 하세요.",
    ],
    [
      "크레딧 소진",
      { ...connected, ...co, scoring_quota_exhausted: true },
      "채점 키의 크레딧이 떨어져 채점이 멈췄습니다 — 소유자가 충전하면 밀린 제출부터 이어서 채점됩니다.",
      "채점 키의 크레딧이 떨어져 채점할 수 없습니다 — 소유자에게 충전해 달라고 하세요.",
    ],
    [
      "원인 모름",
      { ...connected, ...co },
      "채점이 멈춰 있습니다 — 소유자에게 채점 연결을 확인해 달라고 하세요.",
      "지금은 채점할 수 없습니다 — 소유자에게 채점 연결을 확인해 달라고 하세요.",
    ],
  ])("%s — 소유자에게 부탁하는 문장, 설정으로 가는 단추 없음", (_, classroom, submissions, quality) => {
    expect(scoringBlockNote(classroom, "submissions")).toEqual({
      message: submissions,
      actionLabel: null,
    });
    expect(scoringBlockNote(classroom, "quality")).toEqual({
      message: quality,
      actionLabel: null,
    });
  });

  it("서버 연결 불가 — 문장은 소유자와 같고 단추만 없다", () => {
    const classroom = { ...connected, ...co, scoring_server_unreachable: true };

    expect(scoringBlockNote(classroom, "submissions")).toEqual({
      message: scoringBlockNote({ ...classroom, role: "owner" }, "submissions").message,
      actionLabel: null,
    });
  });

  it("소유자는 어느 원인에서나 단추가 있다", () => {
    for (const patch of [{}, { openai_key_status: "rejected" as const }, { scoring_quota_exhausted: true }]) {
      expect(scoringBlockNote({ ...connected, ...patch }, "submissions").actionLabel).not.toBeNull();
    }
    expect(scoringBlockNote(missing, "quality").actionLabel).toBe("클래스 설정에서 넣기");
  });

  it("클래스 정보를 못 읽으면 단추를 내지 않는다", () => {
    expect(scoringBlockNote(null, "quality").actionLabel).toBeNull();
  });
});

describe("modelRejectedNote — 키 사유는 소유자 몫, 모델 사유는 공동 강사도 바꾼다(#1425)", () => {
  const message = "이 키로 쓸 수 없는 채점 모델입니다 — 채점 모델을 바꿔주세요.";

  const action = "채점 모델 바꾸기";

  it("소유자 + 문제 모델 없음 — 클래스 기본 모델(그 문제의 거부도 풀린다)", () => {
    expect(modelRejectedNote("owner", 7, 3, "")).toEqual({ message, actionLabel: action, href: "/classes/7/settings#scoring-model" });
    expect(modelRejectedNote("owner", 7, 3)).toMatchObject({ href: "/classes/7/settings#scoring-model" });
  });

  it("소유자 + 문제 모델 있음 — 문제 편집의 채점 모델 칸(클래스 기본값을 바꿔도 안 풀린다)", () => {
    expect(modelRejectedNote("owner", 7, 3, "gpt-5-retired")).toEqual({
      message,
      actionLabel: action,
      href: "/classes/7/problems/3#scoring-model",
    });
  });

  it("공동 강사 — 문제 모델이 있든 없든 문제 편집의 채점 모델 칸", () => {
    for (const m of ["", "gpt-5-retired"]) {
      expect(modelRejectedNote("co_instructor", 7, 3, m)).toEqual({
        message,
        actionLabel: action,
        href: "/classes/7/problems/3#scoring-model",
      });
    }
  });

  it("역할을 모르면 문구만 — 갈 곳이 열릴지 모른다", () => {
    expect(modelRejectedNote(undefined, 7, 3)).toEqual({
      message,
      actionLabel: null,
      href: null,
    });
  });

  it("채점 키 사유는 공동 강사에게 여전히 소유자에게 부탁한다", () => {
    const co = scoringBlockNote({ ...missing, role: "co_instructor" as const }, "submissions");
    expect(co.actionLabel).toBeNull();
    expect(co.message).toContain("소유자에게");
  });
});

describe("coInstructorCardHint — 채점 카드 (#1431)", () => {
  const co = { ...missing, role: "co_instructor" as const };

  it("공동 강사가 연결 없음만 보면 소유자에게 부탁하는 할 일을 준다", () => {
    expect(coInstructorCardHint(co)).toBe("채점 연결이 없어 채점할 수 없습니다 — 소유자에게 채점 키를 넣어 달라고 하세요.");
  });

  it("소유자·연결됨이면 없다", () => {
    expect(coInstructorCardHint(missing)).toBeNull();
    expect(coInstructorCardHint({ ...connected, role: "co_instructor" })).toBeNull();
  });
});
