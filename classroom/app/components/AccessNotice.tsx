"use client";

// 강의실 404 화면의 안내(#1390) — 화면이 `notFound` 일 때만 그린다. 목록 둘은 여기서
// 읽으므로 이 조각이 새로 뜰 때마다(=404 가 날 때마다) 새로 묻는다. 홈이나 이전 렌더의
// 목록은 쓰이지 않는다. 판정은 `lib/access/notice.ts` 가 한다.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { buttonClass } from "@/app/components/ui";
import { accessNotice, type AccessNoticeContent, type AccessPage } from "@/lib/access/notice";
import { useJoinedClasses } from "@/lib/classes/use-joined-classes";
import { useFormerClasses } from "@/lib/classes/use-former-classes";
import { useMyClasses } from "@/lib/classes/use-my-classes";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";

/** 낡은 404 를 한 번 다시 확인하는 법. */
export type AccessRetry = {
  /** 이 화면의 원래 데이터를 다시 부른다. */
  reload: () => void;
  /** 404 를 낸 조회들의 상태 객체 — 모두 새 객체가 되면 다시 부른 답이 온 것이다. */
  turns: readonly object[];
};

type Props = { classId: number; testId: string; focusOnShow?: boolean; hadAccess?: boolean; wasInstructor?: boolean } & (
  | { page: Extract<AccessPage, "class" | "problem">; retry: AccessRetry }
  | { page: Extract<AccessPage, "mine" | "submit">; retry?: undefined }
);

export function AccessNotice(props: Props) {
  // 다른 클래스로 옮겨 가면 새로 마운트해 목록을 다시 묻는다.
  return <Notice key={`${props.page}:${props.classId}`} {...props} />;
}

function Notice({ page, classId, testId, retry, focusOnShow, hadAccess, wasInstructor }: Props) {
  const joined = useJoinedClasses();
  const taught = useMyClasses();
  const former = useFormerClasses();
  const [turnsBeforeRetry, setTurnsBeforeRetry] = useState<readonly object[] | null>(null);
  const answeredAgain =
    turnsBeforeRetry !== null &&
    retry !== undefined &&
    retry.turns.every((turn, index) => turn !== turnsBeforeRetry[index]);
  const decision = accessNotice({
    page,
    status: answeredAgain ? "retried" : "initial",
    joined,
    taught,
    former,
    hadAccess,
    wasInstructor,
    classId,
  });

  const shouldRetry = decision.kind === "retry" && turnsBeforeRetry === null;
  useEffect(() => {
    if (!shouldRetry || retry === undefined) return;
    setTurnsBeforeRetry(retry.turns);
    retry.reload();
    // 한 번만 부른다 — `retry` 는 렌더마다 새 객체라 의존성에 넣지 않는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shouldRetry]);

  if (decision.kind !== "notice") {
    return (
      <p data-testid="access-notice-loading" className="text-[13.5px] text-ink/45">
        불러오는 중...
      </p>
    );
  }
  return <NoticeBody testId={testId} content={decision} focusOnShow={focusOnShow === true} />;
}

function NoticeBody({
  testId,
  content,
  focusOnShow,
}: {
  testId: string;
  content: AccessNoticeContent;
  focusOnShow: boolean;
}) {
  // 쓰던 폼이 사라지며 안내로 바뀐 경우(#1431)에만 초점을 가져온다 — 처음 열린 화면은 건드리지 않는다.
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focusOnShow) headingRef.current?.focus();
  }, [focusOnShow]);
  // 어느 주소에서 막혔든 탭 제목은 안내 제목이다(#1406) — 화면이 단 제목보다 앞선다.
  useClassroomTabTitle({ screenName: content.title }, { override: true });
  // 「속성.link」 꼴은 공개 저장소 검사(scripts/test_public_repo.py)가 .link 도메인으로 읽는다 — 풀어 쓴다.
  const { link } = content;
  return (
    <>
      <h1 ref={headingRef} tabIndex={-1} data-testid={testId} className="text-[22px] font-semibold outline-none">
        {content.title}
      </h1>
      <p className="mt-4">
        <Link href={link.href} data-testid="access-notice-link" className={buttonClass("secondary", "sm")}>
          {link.label}
        </Link>
      </p>
    </>
  );
}
