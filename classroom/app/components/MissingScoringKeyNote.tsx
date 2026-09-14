// 채점 키가 없다는 사실과 「클래스 설정」으로 가는 길을 알리는 배너(#346/#347).
// 클래스 상세(가입 링크를 공유하기 전에 보여야 하는 자리, #347)와 강사의 제출
// 현황(어느 시도가 그 사유로 멈췄는지, #346)이 문구만 다르게 같은 모양을
// 쓴다 — 손으로 두 곳에 같은 마크업을 베끼면 스타일이나 링크가 갈릴 때
// 한쪽만 고치고 잊기 쉽다.
import Link from "next/link";

import { Note, buttonClass } from "@/app/components/ui";

export function MissingScoringKeyNote({
  classId,
  message,
  noteTestId,
  settingsLinkTestId,
  actionLabel = "클래스 설정에서 넣기",
  settingsAnchor = "scoring-key",
}: {
  classId: number;
  message: string;
  /** 화면마다 이미 자기만의 testid 이름이 있어(#346이 먼저 붙인 것과 #347이
   *  붙인 것이 서로 다르다) 접두어 조립 대신 둘 다 호출부가 그대로 준다. */
  noteTestId: string;
  settingsLinkTestId: string;
  /** 키가 아예 없을 때는 "넣기"가 맞지만, 있는데 거부됐을 때는 "바꾸기"다
   *  (#355) — 기본값은 예전 문구 그대로다. */
  actionLabel?: string;
  /** 클래스 설정 화면의 어느 카드로 스크롤할지(`id` 속성) — 채점 키 문제는
   *  "scoring-key"(기본값), 채점 모델 거부(#403)는 "scoring-model"이다. */
  settingsAnchor?: string;
}) {
  return (
    <Note tone="attention">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span data-testid={noteTestId} className="flex-1">
          {message}
        </span>
        <Link
          href={`/classes/${classId}/settings#${settingsAnchor}`}
          data-testid={settingsLinkTestId}
          className={buttonClass("secondary", "sm")}
        >
          {actionLabel}
        </Link>
      </div>
    </Note>
  );
}
