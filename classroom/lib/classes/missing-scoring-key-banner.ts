// 클래스 상세에서 채점 키 없음 배너(#347)를 띄울지 — 보관된 클래스는 새
// 제출을 받지 않으므로(docs/features/classroom.md 「보관」절) 키가 없어도
// "참여자가 제출해도 채점되지 않습니다"는 일어날 수 없는 일이다(#352).
export function shouldShowMissingScoringKeyBanner(classroom: {
  archived: boolean;
  has_openai_key: boolean;
}): boolean {
  return !classroom.archived && !classroom.has_openai_key;
}

// 키는 있는데 벤더가 거절한 상태(#355) — 「키 없음」과는 다른 배너를 띄운다.
// 강사가 뭘 해야 하는지가 다르다: 없음은 처음 넣어야 하고, 거부됨은 이미
// 넣은 키를 갈아야 한다.
export function shouldShowRejectedScoringKeyBanner(classroom: {
  archived: boolean;
  has_openai_key: boolean;
  openai_key_status: "verified" | "unverified" | "rejected" | null;
}): boolean {
  return !classroom.archived && classroom.has_openai_key && classroom.openai_key_status === "rejected";
}

// 키는 유효한데 그 키의 OpenAI 크레딧이 떨어진 상태(#586) — 갈아 끼울 것이 아니라 충전할
// 것이라 거부 배너와 다른 배너다. 거부됨이 함께면 거부 배너가 먼저다(새 키가 필요하다).
export function shouldShowExhaustedCreditBanner(classroom: {
  archived: boolean;
  has_openai_key: boolean;
  openai_key_status: "verified" | "unverified" | "rejected" | null;
  scoring_quota_exhausted: boolean;
}): boolean {
  return (
    !classroom.archived &&
    classroom.has_openai_key &&
    classroom.openai_key_status !== "rejected" &&
    classroom.scoring_quota_exhausted
  );
}

// 채점 연결의 호환 서버에 닿지 않는 상태(#603) — 크레딧 소진과 같은 모양으로 멈춘다. 서버를
// 살리거나 주소를 고칠 것이라 다른 배너다. 거부됨이 함께면 거부 배너가 먼저다.
export function shouldShowUnreachableServerBanner(classroom: {
  archived: boolean;
  has_openai_key: boolean;
  openai_key_status: "verified" | "unverified" | "rejected" | null;
  scoring_server_unreachable: boolean;
}): boolean {
  return (
    !classroom.archived &&
    classroom.has_openai_key &&
    classroom.openai_key_status !== "rejected" &&
    classroom.scoring_server_unreachable
  );
}
