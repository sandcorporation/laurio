// 가입 링크 미리보기·가입 (#280).
import { backendJson } from "@/lib/backend/client";

export type JoinPreview = {
  class_id: number;
  class_name: string;
  // 강사가 이 클래스에서 불릴 이름으로 정한 값(#299) — 강사 이메일은 더
  // 이상 여기 실리지 않는다. `null`이면(강사가 아직 정하지 않은 예전
  // 클래스) 화면이 이 줄 자체를 생략한다.
  instructor_display_name: string | null;
  problem_count: number;
  participant_count: number;
  // 보관된 클래스인가(#294) — 참이면 화면이 가입 폼 대신 "끝났다" 안내를
  // 보여준다. 죽은 링크(404)와 달리 미리보기 자체는 그대로 온다.
  archived: boolean;
  // 로그인한 사람이 이미 이 클래스의 참여자인가(#300) — 내보내진 사람도
  // 참이다. 참이면 화면이 이름 입력 폼을 건너뛰고 곧장 문제 목록으로 보낸다.
  already_joined: boolean;
  // 이름 칸 기본값으로 쓸 제안 이름(#390) — 로그인한 사람의 카카오
  // 닉네임이다. `null`이면(비로그인, 닉네임 미동의, 카카오가 아닌 제공자)
  // 이름 칸을 빈 채로 둔다 — 직접 적어 가입할 수 있다.
  suggested_name: string | null;
};

export type JoinResult = {
  class_id: number;
  class_name: string;
  display_name: string;
};

export function fetchJoinPreview(code: string): Promise<JoinPreview> {
  return backendJson<JoinPreview>(`/classroom/join/${code}`);
}

export function joinClass(code: string, displayName: string): Promise<JoinResult> {
  return backendJson<JoinResult>(`/classroom/join/${code}`, {
    method: "POST",
    body: JSON.stringify({ display_name: displayName }),
  });
}
