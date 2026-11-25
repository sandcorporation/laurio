// 강의실 404 안내 판정(#1390 D1·D2) — §4.1 표와 우선순위(D4: 강사 → 참여자 → 무관)를 사례로 고정한다.
import { describe, expect, it } from "vitest";

import { accessNotice, type AccessListState, type AccessPage, type AccessStatus } from "./notice";

const CLASS_ID = 7;
const has: AccessListState = { status: "ready", classes: [{ id: 3 }, { id: CLASS_ID }] };
const lacks: AccessListState = { status: "ready", classes: [{ id: 3 }] };
const loading: AccessListState = { status: "loading" };
const failed: AccessListState = { status: "error" };

const PAGES: AccessPage[] = ["class", "problem", "mine", "submit"];
const STATUSES: AccessStatus[] = ["initial", "retried"];

function decide(page: AccessPage, joined: AccessListState, taught: AccessListState, status: AccessStatus = "initial") {
  return accessNotice({ page, status, joined, taught, classId: CLASS_ID });
}

const unrelated = {
  kind: "notice",
  title: "클래스를 찾을 수 없습니다",
  link: { label: "홈으로", href: "/" },
};
const instructorOnly = {
  kind: "notice",
  title: "강사만 볼 수 있는 화면입니다",
  link: { label: "문제 목록으로", href: "/classes/7/problems/mine" },
};
const problemForInstructor = {
  kind: "notice",
  title: "문제를 찾을 수 없습니다",
  link: { label: "클래스로", href: "/classes/7" },
};
const problemForParticipant = {
  kind: "notice",
  title: "문제를 찾을 수 없습니다",
  link: { label: "문제 목록으로", href: "/classes/7/problems/mine" },
};
const notJoined = {
  kind: "notice",
  title: "참여자로 가입하지 않은 클래스입니다",
  link: { label: "클래스로", href: "/classes/7" },
};

describe("두 목록이 다 오기 전에는 정하지 않는다", () => {
  for (const page of PAGES) {
    for (const status of STATUSES) {
      for (const [name, joined, taught] of [
        ["joined 대기", loading, has],
        ["taught 대기", has, loading],
        ["둘 다 대기", loading, loading],
        ["joined 대기 + taught 실패", loading, failed],
        ["taught 대기 + joined 실패", failed, loading],
      ] as const) {
        it(`${page} ${status}: ${name}`, () => {
          expect(decide(page, joined, taught, status)).toEqual({ kind: "pending" });
        });
      }
    }
  }
});

describe("목록 조회 실패는 무관과 같다", () => {
  for (const page of PAGES) {
    for (const status of STATUSES) {
      for (const [name, joined, taught] of [
        ["joined 실패", failed, has],
        ["taught 실패", has, failed],
        ["둘 다 실패", failed, failed],
      ] as const) {
        it(`${page} ${status}: ${name}`, () => {
          expect(decide(page, joined, taught, status)).toEqual(unrelated);
        });
      }
    }
  }
});

describe("어느 목록에도 없으면 무관이다", () => {
  for (const page of PAGES) {
    it(page, () => {
      expect(decide(page, lacks, lacks)).toEqual(unrelated);
    });
  }
});

describe("강사 전용 화면(클래스)", () => {
  it("참여자는 강사 전용 안내", () => {
    expect(decide("class", has, lacks)).toEqual(instructorOnly);
  });
  it("강사 목록에 있으면 404 가 낡은 것 — 한 번 다시 부른다(참여자 행이 있어도 강사가 먼저)", () => {
    expect(decide("class", lacks, has)).toEqual({ kind: "retry" });
    expect(decide("class", has, has)).toEqual({ kind: "retry" });
  });
  it("다시 불러도 404 면 무관과 같다", () => {
    expect(decide("class", lacks, has, "retried")).toEqual(unrelated);
    expect(decide("class", has, has, "retried")).toEqual(unrelated);
  });
});

describe("강사 전용 화면(문제 하나 — 편집·제출 현황)", () => {
  it("참여자는 강사 전용 안내", () => {
    expect(decide("problem", has, lacks)).toEqual(instructorOnly);
  });
  it("강사는 한 번 다시 부르고, 그래도 404 면 문제가 없는 것이다", () => {
    expect(decide("problem", lacks, has)).toEqual({ kind: "retry" });
    expect(decide("problem", has, has, "retried")).toEqual(problemForInstructor);
  });
});

describe("/problems/mine", () => {
  it("강사인데 참여자 행이 없다 — 다시 부르지 않는다", () => {
    expect(decide("mine", lacks, has)).toEqual(notJoined);
  });
  it("강사 목록에 없으면 무관", () => {
    expect(decide("mine", has, lacks)).toEqual(unrelated);
  });
});

describe("/problems/{pid}/submit — taught → joined → 무관", () => {
  it("강사는 「클래스로」, 다시 부르지 않는다", () => {
    expect(decide("submit", lacks, has)).toEqual(problemForInstructor);
  });
  it("참여자는 「문제 목록으로」", () => {
    expect(decide("submit", has, lacks)).toEqual(problemForParticipant);
  });
  it("둘 다 있으면 강사 쪽이다", () => {
    expect(decide("submit", has, has)).toEqual(problemForInstructor);
  });
});
