// 강의실 404 안내 판정(#1390). 백엔드는 비강사에게 404 를 그대로 준다(존재 숨김, #278) —
// 화면은 그 사람이 이미 받는 두 목록(참여 중 `/classes/joined` · 강사 `/classes`)만으로
// 문구와 돌아갈 곳을 고른다. 404 뒤에 새로 받은 목록을 넘겨야 한다(`AccessNotice`).

/** `class`·`problem` 은 강사 전용 화면이다 — `problem` 은 문제 하나를 가리키는 편집·제출 현황. */
export type AccessPage = "class" | "problem" | "mine" | "submit";

/** `retried` 는 원래 화면 데이터를 한 번 다시 불렀는데도 404 인 상태다. */
export type AccessStatus = "initial" | "retried";

export type AccessListState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; classes: readonly { id: number }[] };

export type AccessNoticeContent = {
  kind: "notice";
  title: string;
  link: { label: "홈으로" | "문제 목록으로" | "클래스로"; href: string };
};

export type AccessDecision = { kind: "pending" } | { kind: "retry" } | AccessNoticeContent;

export function accessNotice({
  page,
  status,
  joined,
  taught,
  former,
  hadAccess,
  wasInstructor,
  classId,
}: {
  page: AccessPage;
  status: AccessStatus;
  joined: AccessListState;
  taught: AccessListState;
  /** 한때 강사였던 클래스(#1465 2) — 실패하거나 주지 않으면 이유를 말하지 않는 쪽이다. */
  former?: AccessListState;
  /** 이 화면이 방금까지 열려 있었다(열어 둔 채 접근을 잃었다) — 그 사람은 이미 아는 화면이라 이유를 말해도 새지 않는다. */
  hadAccess?: boolean;
  /** 제출 화면을 강사(학생 화면으로 보기)로 열어 두었다 — 참여자 이력이 겹쳐도 사라진 이유는 문제가 아니라 강사 권한이다(#1471 ③). */
  wasInstructor?: boolean;
  classId: number;
}): AccessDecision {
  const unrelated = notice("클래스를 찾을 수 없습니다", "홈으로", "/");
  // 두 목록이 다 오기 전에는 정하지 않는다 — 최종 문구끼리 바뀌어 보이지 않게.
  if (joined.status === "loading" || taught.status === "loading" || former?.status === "loading") {
    return { kind: "pending" };
  }
  // 하나라도 실패하면 덜 알려 주는 쪽이다.
  if (joined.status === "error" || taught.status === "error") return unrelated;

  const toClass = (title: string) => notice(title, "클래스로", `/classes/${classId}`);
  const toMyProblems = (title: string) => notice(title, "문제 목록으로", `/classes/${classId}/problems/mine`);

  // 강사인지를 먼저 본다 — 참여자 행도 있는 강사에게 백엔드는 강사 경로로 답한다.
  if (taught.classes.some((row) => row.id === classId)) {
    if (page === "mine") return toClass("참여자로 가입하지 않은 클래스입니다");
    if (page === "submit") return toClass("문제를 찾을 수 없습니다");
    // 강사 전용 화면의 404 는 낡았을 수 있다(조회하는 사이 초대 수락).
    if (status === "initial") return { kind: "retry" };
    return page === "problem" ? toClass("문제를 찾을 수 없습니다") : unrelated;
  }
  // 강사에서 빠진 사람에게만 이유를 말한다 — 증거(수락한 초대·이전)가 없는 사람은 아래 「찾을 수 없음」이다(#1465 2).
  const lostInstructorView = page === "submit" && wasInstructor === true;
  if ((page === "class" || page === "problem" || lostInstructorView) && former?.status === "ready" && former.classes.some((row) => row.id === classId)) {
    return notice("더 이상 이 클래스의 강사가 아닙니다", "홈으로", "/");
  }
  const isParticipant = joined.classes.some((row) => row.id === classId);
  // 열어 둔 문제가 사라졌다 — 참여자는 강사가 숨기거나 지운 것이다. 처음부터 없는 주소에는 말하지 않는다.
  if (page === "submit" && isParticipant && hadAccess === true) {
    return toMyProblems("강사가 이 문제를 숨기거나 삭제했습니다");
  }
  if (page === "mine" || !isParticipant) return unrelated;
  return toMyProblems(page === "submit" ? "문제를 찾을 수 없습니다" : "강사만 볼 수 있는 화면입니다");
}

function notice(
  title: string,
  label: AccessNoticeContent["link"]["label"],
  href: string,
): AccessNoticeContent {
  return { kind: "notice", title, link: { label, href } };
}
