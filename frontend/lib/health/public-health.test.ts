import { describe, expect, test } from "vitest";

import { publicHealth } from "./public-health";

describe("publicHealth", () => {
  test("backend 200 이면 200 ok", () => {
    expect(publicHealth({ status: 200, body: '{"status":"ok"}' })).toEqual({ status: 200, body: { status: "ok" } });
  });

  test("backend 503 은 503 그대로, 실패한 점검 이름만 남긴다", () => {
    const reply = { status: 503, body: '{"status":"error","failed":["redis","grader"],"host":"db.internal"}' };
    expect(publicHealth(reply)).toEqual({ status: 503, body: { status: "error", failed: ["redis", "grader"] } });
  });

  test("모르는 이름·내부 문구는 걸러 낸다", () => {
    const reply = { status: 503, body: '{"failed":["password=hunter2","db"]}' };
    expect(publicHealth(reply).body).toEqual({ status: "error", failed: ["db"] });
  });

  test("backend 가 다른 코드(500)·JSON 아닌 본문을 내도 503 으로 바꿔 알린다", () => {
    expect(publicHealth({ status: 500, body: "Traceback ..." })).toEqual({
      status: 503,
      body: { status: "error", failed: ["backend"] },
    });
  });

  test("닿지 않으면 503 backend", () => {
    expect(publicHealth(null)).toEqual({ status: 503, body: { status: "error", failed: ["backend"] } });
  });
});
