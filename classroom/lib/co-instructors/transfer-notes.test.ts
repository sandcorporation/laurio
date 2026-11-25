import { describe, expect, it } from "vitest";

import type { NotificationRow } from "../notifications/api";
import { describeNotification } from "../notifications/format";
import { takenOverNoteText } from "./transfer-notes";

describe("takenOverNoteText (#1441 5번)", () => {
  it("취소를 누른 뒤라면 「이미 넘겨받았습니다」로 말한다", () => {
    expect(takenOverNoteText("박조교", true)).toBe(
      "이미 박조교님이 넘겨받았습니다 — 요청은 취소되지 않았고, 이제 나는 이 클래스의 공동 강사입니다.",
    );
  });

  it("누르지 않았어도 소유자가 바뀌면 알린다", () => {
    expect(takenOverNoteText("박조교", false)).toBe("박조교님이 소유권을 넘겨받았습니다 — 이제 나는 이 클래스의 공동 강사입니다.");
  });

  it("이름이 없으면 조사가 달라진다", () => {
    expect(takenOverNoteText("", true)).toContain("이미 받는 사람이 넘겨받았습니다");
  });
});

describe("알림 문구와의 주어 (#1455 1번)", () => {
  it("알림의 「이제 나는 …」 꼬리와 글자까지 같다", () => {
    const notice = describeNotification({
      id: 1,
      notification_type: "classroom_ownership_transfer_accepted",
      is_transactional: true,
      is_promotional: false,
      status: "not_dispatched",
      context: { class_name: "반", recipient_display_name: "박조교" },
    } as unknown as NotificationRow);
    const tail = notice.split(" — ")[1];
    expect(takenOverNoteText("박조교", false).split(" — ")[1]).toBe(tail);
  });
});
