import { describe, expect, it } from "vitest";

import { cancelTransferButtonLabel, removeButtonLabel, transferButtonLabel } from "./instructor-labels";

describe("강사 줄 단추 이름 (#1441 10번)", () => {
  it.each(["공동이", "박조교", "Kim", "이름 없음"])("받침·끝 글자와 상관없이 %s 는 대상으로 읽힌다", (name) => {
    expect(transferButtonLabel(name)).toBe(`${name}에게 소유권 넘기기`);
    expect(cancelTransferButtonLabel(name)).toBe(`${name}에게 보낸 소유권 이전 요청 취소`);
  });

  it("내보내기는 역할이 앞에 붙어 이름이 주어로 들리지 않는다", () => {
    expect(removeButtonLabel("공동이")).toBe("공동 강사 공동이 내보내기");
    expect(removeButtonLabel("공동이")).not.toMatch(/^공동이 /);
  });
});
