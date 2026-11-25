import { describe, expect, it } from "vitest";

import type { NotificationRow } from "../notifications/api";
import { describeNotification } from "../notifications/format";

import { scoringBlockNote } from "./scoring-block-note";

const connected = {
  archived: false,
  has_openai_key: true,
  openai_key_status: "verified" as const,
  scoring_quota_exhausted: false,
  scoring_server_unreachable: false,
  scoring_connection_kind: "openai_key",
  openai_key_masked: "sk-…7f2a",
  scoring_server_host: null,
};

const missing = { ...connected, has_openai_key: false, openai_key_status: null, openai_key_masked: null };

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
