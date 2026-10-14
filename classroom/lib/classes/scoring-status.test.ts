import { describe, expect, it } from "vitest";

import { SCORING_STATUS_LABEL, scoringStatus, settingsStatusBadges } from "./scoring-status";

const base = {
  archived: false,
  has_openai_key: true,
  openai_key_status: "verified" as const,
  scoring_quota_exhausted: false,
  scoring_server_unreachable: false,
  scoring_connection_kind: "openai_key",
  openai_key_masked: "sk-…7f2a",
  scoring_server_host: null,
};

describe("scoringStatus — 배너 넷의 조건 그대로", () => {
  it("멀쩡하면 연결됨과 종류·마스킹이다", () => {
    expect(scoringStatus(base)).toEqual({ kind: "connected", connection: "OpenAI 키 · sk-…7f2a" });
  });

  it("호환 서버는 호스트를 적는다", () => {
    expect(
      scoringStatus({ ...base, scoring_connection_kind: "compatible_server", scoring_server_host: "llm.example.kr" }),
    ).toEqual({ kind: "connected", connection: "호환 서버 · llm.example.kr" });
  });

  it("키가 없으면 연결 없음(문제)", () => {
    expect(scoringStatus({ ...base, has_openai_key: false, openai_key_status: null })).toEqual({
      kind: "missing",
      problem: true,
    });
  });

  it("보관된 클래스는 키가 없어도 문제로 치지 않는다", () => {
    expect(scoringStatus({ ...base, archived: true, has_openai_key: false, openai_key_status: null })).toEqual({
      kind: "missing",
      problem: false,
    });
  });

  it("거부됨이 크레딧 소진·서버 불가보다 먼저다", () => {
    expect(
      scoringStatus({ ...base, openai_key_status: "rejected", scoring_quota_exhausted: true, scoring_server_unreachable: true }),
    ).toEqual({ kind: "rejected" });
  });

  it("크레딧 소진, 서버 연결 불가", () => {
    expect(scoringStatus({ ...base, scoring_quota_exhausted: true })).toEqual({ kind: "exhausted" });
    expect(scoringStatus({ ...base, scoring_server_unreachable: true })).toEqual({ kind: "unreachable" });
  });
});

describe("settingsStatusBadges — 설정의 상태 한 줄은 카드와 같은 낱말이다(#669)", () => {
  it("키가 없으면 카드와 같은 「연결 없음」", () => {
    expect(settingsStatusBadges({ ...base, has_openai_key: false, openai_key_status: null })).toEqual([
      { label: SCORING_STATUS_LABEL.missing, tone: "attention" },
    ]);
  });

  it("호환 서버에 닿지 못하면 카드와 같은 「서버 연결 불가」", () => {
    expect(
      settingsStatusBadges({
        ...base,
        scoring_connection_kind: "compatible_server",
        scoring_server_host: "llm.example.kr",
        scoring_server_unreachable: true,
      }),
    ).toEqual([{ label: SCORING_STATUS_LABEL.unreachable, tone: "attention" }]);
  });

  it("보관된 클래스의 연결 없음은 문제 톤이 아니다", () => {
    expect(settingsStatusBadges({ ...base, archived: true, has_openai_key: false, openai_key_status: null })).toEqual([
      { label: SCORING_STATUS_LABEL.missing, tone: "neutral" },
    ]);
  });

  it("검증 전 OpenAI 키는 「연결됨」에 「미검증」만 덧붙인다", () => {
    expect(settingsStatusBadges({ ...base, openai_key_status: "unverified" })).toEqual([
      { label: SCORING_STATUS_LABEL.connected, tone: "verified" },
      { label: "미검증", tone: "neutral" },
    ]);
  });
});
